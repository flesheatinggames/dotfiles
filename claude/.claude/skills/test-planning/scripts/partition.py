#!/usr/bin/env python3
"""Partition the work above the value line into target areas for the claims fan-out.

R-5.2 says claims derivation runs as parallel subagents, one per target area, partitioned
"per assessment finding or per module, whichever partitions the code more cleanly". This
script answers *which* deterministically rather than by eye, and then packs the areas so
the readers finish at roughly the same time.

It produces three things:

* a **finding-to-file map** built from the findings above the value line and the
  recommendations that address them;
* **collision counts** — how many findings touch each file. This is what decides the
  partitioning axis: when findings share files heavily, a per-finding split sends the same
  file to several readers, who then derive the same claims independently and the merge has
  to sort it out;
* **bin-packed areas**, balanced by line count using longest-first greedy packing, the same
  method the assessment skill uses to partition test files.

It also emits a **ledger**: every file, and every symbol where symbol names are available,
that the derivation pass is accountable for. `merge_claims.py` checks the merged claim set
against this ledger, which is what stops a reader quietly skipping half its area.

Usage:
    python3 partition.py --assessment docs/test-assessment.md --repo . --json
    python3 partition.py --assessment docs/test-assessment.md --repo . --value-line top \\
                         --areas 4 --complexity /tmp/cx.json --json
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import read_assessment  # noqa: E402

TIER_ORDER = ["top", "high", "medium", "low"]
LOCATION_RE = re.compile(r"^(?P<path>[^:]+?)(?::(?P<line>\d+))?$")

# Above this share of files touched by more than one finding, a per-finding split sends the
# same file to several readers. The threshold is a judgment; what matters is that the same
# input always produces the same answer, and that the reasoning is visible in the output.
COLLISION_THRESHOLD = 0.35


def strip_location(location):
    """`src/lib/a.ts:41` -> `src/lib/a.ts`. Leaves a bare path alone."""
    match = LOCATION_RE.match(location.strip())
    return match.group("path") if match else location.strip()


def module_of(path):
    """The directory a file belongs to, used as the per-module partitioning key."""
    directory = os.path.dirname(path)
    return directory or "."


def line_count(repo, path):
    """Lines in a file, or None when it cannot be read. Never raises."""
    full = os.path.join(repo, path)
    try:
        with open(full, "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return None


def build_map(index, value_line):
    """Return (finding_files, recommendation_files, files_by_finding_id)."""
    cutoff = TIER_ORDER.index(value_line)
    findings = {
        f["id"]: f
        for f in index.get("findings", [])
        if isinstance(f, dict)
        and f.get("tier") in TIER_ORDER
        and TIER_ORDER.index(f["tier"]) <= cutoff
    }

    files_by_finding = {}
    for finding_id, finding in findings.items():
        paths = {strip_location(p) for p in finding.get("files", []) if isinstance(p, str)}
        files_by_finding[finding_id] = paths

    for rec in index.get("recommendations", []) or []:
        if not isinstance(rec, dict):
            continue
        addressed = [f for f in rec.get("addresses", []) if f in findings]
        if not addressed:
            continue
        paths = {strip_location(p) for p in rec.get("locations", []) if isinstance(p, str)}
        for finding_id in addressed:
            files_by_finding[finding_id] |= paths

    return findings, files_by_finding


def collision_report(files_by_finding):
    owners = {}
    for finding_id, paths in files_by_finding.items():
        for path in paths:
            owners.setdefault(path, set()).add(finding_id)
    shared = {path: sorted(ids) for path, ids in owners.items() if len(ids) > 1}
    total = len(owners) or 1
    return {
        "files_total": len(owners),
        "files_shared": len(shared),
        "share": round(len(shared) / total, 3),
        "shared_files": dict(sorted(shared.items())),
    }


def choose_axis(collisions, files_by_finding):
    if not files_by_finding:
        return "per-finding", "there is nothing above the value line to partition"
    if collisions["share"] > COLLISION_THRESHOLD:
        return "per-module", (
            f"{collisions['files_shared']} of {collisions['files_total']} files are touched "
            f"by more than one finding ({collisions['share']:.0%}, above the "
            f"{COLLISION_THRESHOLD:.0%} threshold). A per-finding split would send the same "
            "file to several readers, who would derive the same claims independently"
        )
    return "per-finding", (
        f"only {collisions['files_shared']} of {collisions['files_total']} files are touched "
        f"by more than one finding ({collisions['share']:.0%}), so the findings partition the "
        "code cleanly on their own"
    )


def build_units(axis, findings, files_by_finding):
    """A unit is one thing to be packed into an area: a finding, or a module."""
    units = []
    if axis == "per-finding":
        for finding_id in sorted(files_by_finding, key=lambda i: findings[i].get("rank", 999)):
            units.append(
                {
                    "key": finding_id,
                    "findings": [finding_id],
                    "files": sorted(files_by_finding[finding_id]),
                }
            )
        return units

    by_module = {}
    for finding_id, paths in files_by_finding.items():
        for path in paths:
            entry = by_module.setdefault(module_of(path), {"files": set(), "findings": set()})
            entry["files"].add(path)
            entry["findings"].add(finding_id)
    for module in sorted(by_module):
        units.append(
            {
                "key": module,
                "findings": sorted(by_module[module]["findings"]),
                "files": sorted(by_module[module]["files"]),
            }
        )
    return units


def weigh(units, repo):
    for unit in units:
        measured = [(path, line_count(repo, path)) for path in unit["files"]]
        unit["file_sizes"] = {path: size for path, size in measured}
        # A file that cannot be read counts as a nominal 200 lines rather than zero, so an
        # area of unreadable files is not treated as free.
        unit["weight"] = sum(size if size is not None else 200 for _, size in measured)
        unit["unreadable"] = sorted(p for p, size in measured if size is None)
    return units


def split_oversized(units, cap):
    """Split any unit larger than the cap into several, packing its files longest-first.

    Without this, a single large module becomes a single area, and no number of areas can
    balance it. One real case: a nine-file test module of 10,231 lines, against a reading
    threshold of roughly 6,000 lines per reader. The split is by file, so no file is ever
    given to two readers and the disjointness the fan-out depends on is preserved.
    """
    result = []
    for unit in units:
        if unit["weight"] <= cap or len(unit["files"]) <= 1:
            result.append(unit)
            continue
        parts = max(2, -(-unit["weight"] // cap))
        bins = [{"files": [], "weight": 0} for _ in range(parts)]
        for path in sorted(unit["files"], key=lambda p: (-(unit["file_sizes"].get(p) or 200), p)):
            target = min(bins, key=lambda b: (b["weight"], bins.index(b)))
            target["files"].append(path)
            target["weight"] += unit["file_sizes"].get(path) or 200
        for i, container in enumerate(bins, start=1):
            if not container["files"]:
                continue
            result.append(
                {
                    "key": f"{unit['key']}#{i}",
                    "findings": unit["findings"],
                    "files": sorted(container["files"]),
                    "file_sizes": {p: unit["file_sizes"].get(p) for p in container["files"]},
                    "weight": container["weight"],
                    "unreadable": sorted(p for p in container["files"] if unit["file_sizes"].get(p) is None),
                    "split_from": unit["key"],
                }
            )
    return result


def pack(units, repo, area_count):
    """Longest-first greedy bin packing, balanced by line count.

    Balancing by lines rather than by file count is the same rule the assessment skill uses
    for test reading, and for the same reason: one 3,000-line file outweighs six 300-line
    ones, and a split by count leaves one reader with most of the work.
    """
    ordered = sorted(units, key=lambda u: (-u["weight"], u["key"]))
    area_count = max(1, min(area_count, len(ordered) or 1))
    bins = [{"units": [], "weight": 0} for _ in range(area_count)]

    for unit in ordered:
        target = min(bins, key=lambda b: (b["weight"], bins.index(b)))
        target["units"].append(unit)
        target["weight"] += unit["weight"]

    areas = []
    for i, container in enumerate(bins, start=1):
        if not container["units"]:
            continue
        files = sorted({path for unit in container["units"] for path in unit["files"]})
        findings = sorted({f for unit in container["units"] for f in unit["findings"]})
        areas.append(
            {
                "id": f"A{i}",
                "keys": sorted(unit["key"] for unit in container["units"]),
                "findings": findings,
                "files": files,
                "lines": container["weight"],
                "unreadable": sorted(
                    {p for unit in container["units"] for p in unit["unreadable"]}
                ),
                "split_units": sorted(
                    unit["key"] for unit in container["units"] if unit.get("split_from")
                ),
            }
        )
    return areas


def load_symbols(complexity_path):
    """Per-file function names from the assessment skill's complexity.py output."""
    if not complexity_path:
        return {}
    try:
        with open(complexity_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    symbols = {}
    for entry in data.get("files", []) or []:
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        names = [
            fn.get("name")
            for fn in entry.get("functions", []) or []
            if isinstance(fn, dict) and isinstance(fn.get("name"), str)
        ]
        symbols[path] = sorted({n for n in names if n and n != "<anonymous>"})
    return symbols, bool(data.get("counts_are_exact"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--assessment", required=True, help="path to the assessment report")
    parser.add_argument("--repo", default=".", help="repository root, for measuring file sizes")
    parser.add_argument("--value-line", choices=TIER_ORDER, help="override the suggested value line")
    parser.add_argument("--areas", type=int, default=5, help="how many areas to pack into (default 5)")
    parser.add_argument(
        "--max-area-lines",
        type=int,
        default=6000,
        help="split a unit larger than this across several areas (default 6000, the same "
             "threshold the assessment skill uses to decide when to fan out)",
    )
    parser.add_argument(
        "--axis",
        choices=["per-finding", "per-module", "auto"],
        default="auto",
        help="override the partitioning axis (default: choose from the collision counts)",
    )
    parser.add_argument("--complexity", help="complexity.py JSON, to build a symbol-level ledger")
    parser.add_argument("--json", action="store_true", help="emit as JSON")
    args = parser.parse_args()

    try:
        index = read_assessment.read_index(args.assessment)
    except read_assessment.AssessmentError as error:
        print(f"STOP: {error.message}\n", file=sys.stderr)
        if error.instruction:
            print(error.instruction, file=sys.stderr)
        return 2

    summary = read_assessment.summarize(index, args.value_line)
    value_line = summary["value_line"]

    findings, files_by_finding = build_map(index, value_line)
    collisions = collision_report(files_by_finding)
    chosen_axis, axis_reason = choose_axis(collisions, files_by_finding)
    if args.axis != "auto":
        axis_reason = f"overridden on the command line (auto would have chosen {chosen_axis}: {axis_reason})"
        chosen_axis = args.axis

    units = weigh(build_units(chosen_axis, findings, files_by_finding), args.repo)
    oversized = [u["key"] for u in units if u["weight"] > args.max_area_lines]
    units = split_oversized(units, args.max_area_lines)
    areas = pack(units, args.repo, max(args.areas, len(units) if oversized else args.areas))

    symbols, exact = ({}, False)
    if args.complexity:
        loaded = load_symbols(args.complexity)
        if isinstance(loaded, tuple):
            symbols, exact = loaded

    ledger = []
    for area in areas:
        for path in area["files"]:
            ledger.append(
                {
                    "area": area["id"],
                    "file": path,
                    "symbols": symbols.get(path, []),
                    "symbols_exact": exact if path in symbols else None,
                }
            )

    result = {
        "assessment": args.assessment,
        "repository": index.get("repository"),
        "value_line": value_line,
        "axis": chosen_axis,
        "axis_reason": axis_reason,
        "collisions": collisions,
        "areas": areas,
        "ledger": ledger,
        "ledger_granularity": "symbol" if symbols else "file",
        "split_units": oversized,
        "max_area_lines": args.max_area_lines,
        "warnings": summary["warnings"]
        + (
            [
                "Split because they exceeded the "
                f"{args.max_area_lines}-line cap: {', '.join(oversized)}. Each part is a "
                "separate reader with a disjoint file list, so no file goes to two readers."
            ]
            if oversized
            else []
        ),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"{result['repository']}: value line `{value_line}`, axis `{chosen_axis}`")
    print(f"  {axis_reason}")
    print(
        f"  collisions: {collisions['files_shared']} of {collisions['files_total']} files "
        f"touched by more than one finding"
    )
    print(f"  {len(areas)} area(s), ledger at {result['ledger_granularity']} granularity:")
    for area in areas:
        print(
            f"    {area['id']}: {', '.join(area['findings'])} — {len(area['files'])} file(s), "
            f"{area['lines']:,} lines"
        )
        for path in area["files"]:
            names = symbols.get(path, [])
            suffix = f"  [{len(names)} symbol(s)]" if names else ""
            print(f"        {path}{suffix}")
        if area["unreadable"]:
            print(f"        unreadable, weighted at 200 lines each: {', '.join(area['unreadable'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

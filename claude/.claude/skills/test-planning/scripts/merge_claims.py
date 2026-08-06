#!/usr/bin/env python3
"""Merge the claims-derivation readers' output into one ratification list.

R-5.3 requires a merge step that "deduplicates claims that multiple areas derived from the
same document statement, preserving every location the claim applies to". This does that,
assigns each surviving claim a stable identifier, and then checks the two arithmetic gates
that decide whether the derivation pass actually finished.

**Gate A — ledger completeness.** Every file the partition made the readers accountable for
must be named by at least one claim, or be accounted for by an explicit reason for having no
claim. Where symbol names were available, the same applies per symbol. This is what catches a
reader that quietly read half its area: nothing else would, because a short answer looks
exactly like a small area.

**Gate B — claim budget.** The total must fit the slice sizing heuristic: at most eight
slices carrying eight to twenty-five claims each, so roughly two hundred. Going over does not
mean dropping claims. It means the value line was set too low for one review sitting, and the
right response is to raise it and re-partition, which is a decision the plan records rather
than a corner it cuts.

Usage:
    python3 merge_claims.py area-*.json --ledger /tmp/partition.json --json
    python3 merge_claims.py area-*.json --ledger /tmp/partition.json --emit-yaml
"""

import argparse
import glob
import json
import os
import re
import sys

MAX_SLICES = 8
MAX_CLAIMS_PER_SLICE = 25
MIN_CLAIMS_PER_SLICE = 8
CLAIM_BUDGET = MAX_SLICES * MAX_CLAIMS_PER_SLICE

LABELS = ("cited", "pinned")
LABEL_RANK = {"cited": 0, "pinned": 1}
CONFLICT_CLASSES = ("flagged", "escalation", "decision", "inconsistent-pinned-pair")


def normalize(text):
    """Lowercase, collapse whitespace, drop a trailing period. Used only for comparison."""
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip(".")


def strip_line(location):
    return (location or "").split(":")[0].strip()


def load_area(path, problems):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        problems.append(f"{path}: could not read: {error}")
        return None
    if not isinstance(data, dict):
        problems.append(f"{path}: expected an object at the top level")
        return None
    data.setdefault("area", os.path.basename(path))
    for key in ("claims", "conflicts", "no_claim_reasons", "files_read", "symbols_examined"):
        data.setdefault(key, [])
    return data


def validate_claim(claim, area, index, problems):
    where = f"{area} claim {index + 1}"
    if not isinstance(claim, dict):
        problems.append(f"{where}: not an object")
        return False
    ok = True
    text = claim.get("text")
    if not isinstance(text, str) or len(text.strip()) < 20:
        problems.append(
            f"{where}: `text` is missing or too short to write a test from"
        )
        ok = False
    if claim.get("label") not in LABELS:
        problems.append(
            f"{where}: `label` must be `cited` or `pinned`, got {claim.get('label')!r}. "
            "`ratified` only ever results from owner review."
        )
        ok = False
    source = claim.get("source")
    if not isinstance(source, dict):
        problems.append(f"{where}: `source` is missing")
        return False
    if source.get("kind") not in ("document", "code"):
        problems.append(f"{where}: `source.kind` must be `document` or `code`")
        ok = False
    if not (source.get("location") or "").strip():
        problems.append(f"{where}: `source.location` is empty; an unsourceable claim is not emitted")
        ok = False
    if claim.get("label") == "cited" and not (source.get("quote") or "").strip():
        problems.append(
            f"{where}: a cited claim must carry the document's words inline. The reviewer "
            "has to be able to check the label without opening the repository."
        )
        ok = False
    if claim.get("label") == "cited" and source.get("kind") != "document":
        problems.append(f"{where}: labelled `cited` but sourced to code")
        ok = False
    if claim.get("label") == "pinned" and source.get("kind") != "code":
        problems.append(f"{where}: labelled `pinned` but sourced to a document")
        ok = False
    locations = claim.get("locations")
    if not isinstance(locations, list) or not locations:
        problems.append(f"{where}: `locations` must name at least one place the claim applies")
        ok = False
    else:
        for location in locations:
            if isinstance(location, str) and (location.startswith("/") or location.startswith("~")):
                problems.append(f"{where}: absolute location {location!r}")
                ok = False
    return ok


def merge(areas, problems):
    """Deduplicate and union. Returns (claims, possible_duplicates)."""
    buckets = {}
    for area in areas:
        for i, claim in enumerate(area["claims"]):
            if not validate_claim(claim, area["area"], i, problems):
                continue
            source = claim["source"]
            key = (claim["label"], source["kind"], source["location"].strip(), normalize(claim["text"]))
            bucket = buckets.setdefault(
                key,
                {
                    "text": claim["text"].strip(),
                    "label": claim["label"],
                    "source": {
                        "kind": source["kind"],
                        "location": source["location"].strip(),
                        "quote": (source.get("quote") or "").strip() or None,
                    },
                    "locations": set(),
                    "symbols": set(),
                    "areas": set(),
                    "notes": [],
                },
            )
            bucket["locations"] |= {str(loc).strip() for loc in claim["locations"]}
            bucket["symbols"] |= {
                str(symbol).strip() for symbol in claim.get("symbols", []) or []
            }
            bucket["areas"].add(area["area"])
            note = (claim.get("notes") or "").strip()
            if note and note not in bucket["notes"]:
                bucket["notes"].append(note)
            if bucket["source"]["quote"] is None and (source.get("quote") or "").strip():
                bucket["source"]["quote"] = source["quote"].strip()

    ordered = sorted(
        buckets.items(),
        key=lambda kv: (LABEL_RANK[kv[0][0]], kv[0][2], kv[0][3]),
    )

    claims = []
    for position, (_, bucket) in enumerate(ordered, start=1):
        claims.append(
            {
                "id": f"C{position}",
                "text": bucket["text"],
                "label": bucket["label"],
                "source": bucket["source"],
                "locations": sorted(bucket["locations"]),
                "symbols": sorted(bucket["symbols"]),
                "derived_by": sorted(bucket["areas"]),
                "notes": bucket["notes"],
            }
        )

    # Two claims citing the same document passage with different wording are not merged,
    # because two requirements often live in one section. They are reported so a person
    # decides rather than the script guessing.
    by_source = {}
    for claim in claims:
        by_source.setdefault((claim["source"]["kind"], claim["source"]["location"]), []).append(claim["id"])
    possible_duplicates = {
        f"{kind} {location}": ids for (kind, location), ids in sorted(by_source.items()) if len(ids) > 1
    }

    return claims, possible_duplicates


def gate_ledger(claims, areas, ledger, granularity):
    """Gate A: everything the readers were accountable for is claimed or accounted for."""
    claimed_files = set()
    claimed_symbols = set()
    for claim in claims:
        for location in claim["locations"]:
            claimed_files.add(strip_line(location))
        claimed_symbols |= set(claim["symbols"])

    excused_files = set()
    excused_symbols = set()
    for area in areas:
        for entry in area["no_claim_reasons"]:
            if not isinstance(entry, dict) or not (entry.get("reason") or "").strip():
                continue
            if entry.get("file"):
                excused_files.add(strip_line(entry["file"]))
            if entry.get("symbol"):
                excused_symbols.add(entry["symbol"].strip())

    ledger_files = {entry["file"] for entry in ledger if isinstance(entry, dict) and entry.get("file")}
    unaccounted_files = sorted(ledger_files - claimed_files - excused_files)

    unaccounted_symbols = []
    if granularity == "symbol":
        for entry in ledger:
            if not isinstance(entry, dict):
                continue
            for symbol in entry.get("symbols", []) or []:
                if symbol not in claimed_symbols and symbol not in excused_symbols:
                    unaccounted_symbols.append(f"{entry['file']}::{symbol}")

    examined_unaccounted = []
    for area in areas:
        for symbol in area["symbols_examined"]:
            name = str(symbol).strip()
            if name and name not in claimed_symbols and name not in excused_symbols:
                examined_unaccounted.append(f"{area['area']}::{name}")

    passed = not unaccounted_files and not unaccounted_symbols and not examined_unaccounted
    return {
        "name": "Gate A — ledger completeness",
        "passed": passed,
        "ledger_files": len(ledger_files),
        "unaccounted_files": unaccounted_files,
        "unaccounted_symbols": sorted(set(unaccounted_symbols)),
        "examined_but_unaccounted": sorted(set(examined_unaccounted)),
        "remedy": (
            "Every file and symbol the partition made a reader accountable for must either "
            "be named by a claim or carry an explicit reason for having none. Re-run the "
            "reader for the unaccounted area, or record the reason. Do not close the gap by "
            "removing entries from the ledger."
        )
        if not passed
        else None,
    }


def gate_budget(claims):
    total = len(claims)
    minimum_slices = max(1, -(-total // MAX_CLAIMS_PER_SLICE))
    passed = total <= CLAIM_BUDGET
    return {
        "name": "Gate B — claim budget",
        "passed": passed,
        "claims": total,
        "budget": CLAIM_BUDGET,
        "slices_implied": minimum_slices,
        "sizing": f"{MIN_CLAIMS_PER_SLICE}-{MAX_CLAIMS_PER_SLICE} claims per slice, at most {MAX_SLICES} slices",
        "remedy": (
            f"{total} claims exceeds the {CLAIM_BUDGET} the sizing heuristic allows, which "
            "means the value line is set too low for one review sitting. Raise the value "
            "line, re-partition, and record the narrower scope in the plan's exclusions. Do "
            "not drop claims silently to fit."
        )
        if not passed
        else None,
    }


def collect_conflicts(areas, claims, problems):
    by_class = {name: [] for name in CONFLICT_CLASSES}
    symbol_to_claim = {}
    for claim in claims:
        for symbol in claim["symbols"]:
            symbol_to_claim.setdefault(symbol, []).append(claim["id"])

    for area in areas:
        for i, conflict in enumerate(area["conflicts"]):
            if not isinstance(conflict, dict):
                problems.append(f"{area['area']} conflict {i + 1}: not an object")
                continue
            kind = conflict.get("class")
            if kind not in CONFLICT_CLASSES:
                problems.append(
                    f"{area['area']} conflict {i + 1}: `class` must be one of "
                    f"{list(CONFLICT_CLASSES)}, got {kind!r}"
                )
                continue
            entry = dict(conflict)
            entry["area"] = area["area"]
            if kind == "inconsistent-pinned-pair":
                symbols = [str(s).strip() for s in conflict.get("symbols", []) or []]
                resolved = sorted({cid for s in symbols for cid in symbol_to_claim.get(s, [])})
                entry["claims"] = resolved
                if len(resolved) < 2:
                    problems.append(
                        f"{area['area']} conflict {i + 1}: an inconsistent-pinned-pair needs "
                        "two pinned claims to group, and only "
                        f"{len(resolved)} of its symbols {symbols} matched a claim"
                    )
            by_class[kind].append(entry)

    seen = set()
    for kind, entries in by_class.items():
        deduped = []
        for entry in entries:
            key = (kind, normalize(entry.get("title", "")), entry.get("code", {}).get("location") if isinstance(entry.get("code"), dict) else None)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        by_class[kind] = deduped
    return by_class


def yaml_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_yaml(claims):
    out = []
    for claim in claims:
        out.append("```yaml claim")
        out.append(f"id: {claim['id']}")
        out.append(f"text: {yaml_quote(claim['text'])}")
        out.append(f"label: {claim['label']}")
        out.append("source:")
        out.append(f"  kind: {claim['source']['kind']}")
        out.append(f"  location: {yaml_quote(claim['source']['location'])}")
        if claim["source"]["quote"]:
            out.append(f"  quote: {yaml_quote(claim['source']['quote'])}")
        out.append("locations:")
        for location in claim["locations"]:
            out.append(f"  - {yaml_quote(location)}")
        if claim["notes"]:
            out.append("notes: >")
            for note in claim["notes"]:
                for line in note.splitlines():
                    out.append(f"  {line.strip()}")
        out.append("```")
        out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("areas", nargs="+", help="the readers' JSON output files (globs allowed)")
    parser.add_argument("--ledger", help="partition.py JSON, for Gate A")
    parser.add_argument("--json", action="store_true", help="emit the merged result as JSON")
    parser.add_argument("--emit-yaml", action="store_true", help="print claim blocks ready to paste")
    args = parser.parse_args()

    paths = []
    for pattern in args.areas:
        expanded = sorted(glob.glob(pattern))
        paths.extend(expanded or [pattern])

    problems = []
    areas = [a for a in (load_area(p, problems) for p in sorted(set(paths))) if a]
    if not areas:
        print("no readable area files", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 2

    claims, possible_duplicates = merge(areas, problems)

    ledger, granularity = [], "file"
    if args.ledger:
        try:
            with open(args.ledger, encoding="utf-8") as handle:
                partition = json.load(handle)
            ledger = partition.get("ledger", [])
            granularity = partition.get("ledger_granularity", "file")
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{args.ledger}: could not read the ledger: {error}")

    gates = [gate_ledger(claims, areas, ledger, granularity), gate_budget(claims)]
    conflicts = collect_conflicts(areas, claims, problems)

    result = {
        "areas_merged": [a["area"] for a in areas],
        "claims_in": sum(len(a["claims"]) for a in areas),
        "claims_out": len(claims),
        "deduplicated": sum(len(a["claims"]) for a in areas) - len(claims),
        "claims": claims,
        "possible_duplicates": possible_duplicates,
        "conflicts": conflicts,
        "gates": gates,
        "problems": problems,
        "ok": not problems and all(gate["passed"] for gate in gates),
    }

    if args.emit_yaml:
        print(emit_yaml(claims))
        return 0 if result["ok"] else 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    print(
        f"merged {len(areas)} area(s): {result['claims_in']} claims in, "
        f"{result['claims_out']} out ({result['deduplicated']} deduplicated)"
    )
    cited = sum(1 for c in claims if c["label"] == "cited")
    print(f"  {cited} cited, {len(claims) - cited} pinned — the pinned ones go to ratification")
    for kind, entries in conflicts.items():
        if entries:
            print(f"  {kind}: {len(entries)}")
    if possible_duplicates:
        print("  possible duplicates, same source and different wording — check by hand:")
        for source, ids in possible_duplicates.items():
            print(f"    {source}: {', '.join(ids)}")
    for gate in gates:
        status = "pass" if gate["passed"] else "FAIL"
        print(f"  [{status}] {gate['name']}")
        if not gate["passed"]:
            for key in ("unaccounted_files", "unaccounted_symbols", "examined_but_unaccounted"):
                if gate.get(key):
                    print(f"      {key}: {', '.join(gate[key][:12])}")
            print(f"      {gate['remedy']}")
    if problems:
        print(f"  {len(problems)} problem(s) in the readers' output:")
        for problem in problems:
            print(f"    - {problem}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

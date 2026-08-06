#!/usr/bin/env python3
"""What an item actually did, read from the repository rather than from self-report (R-9.1).

Three facts, from three sources that are not the executor:

* **Files touched**, from the git diff of the item's commit. Not from a list the executor
  kept while it worked, because that list is a memory of intentions.
* **Check outcomes**, from the check runner's output, passed straight through.
* **Timings**, from the clock.

**The reason this is measured rather than reported is planning R-10.3.** That requirement
gates any future concurrent execution on declared footprints matching actual ones, and the
whole measurement is worthless if the party being measured supplies the figures. R-2.2 is the
other half of the same idea from the other direction: an item that touched something outside
its footprint fails, and does not get to widen the footprint to match.

Usage:
    python3 actuals.py <plan> --item WI-04 --commit 1d9f8e2 --repo . \\
            --checks checks.json --attempts 3 --started ... --finished ... --json
    python3 actuals.py <plan> --item WI-04 --commit HEAD --repo . --footprint-only
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planio  # noqa: E402

# How a path is classified when the item's declared footprint does not name it — which is the
# only case that matters, because a path the footprint names is classified by the footprint.
# An unclassified path is a footprint violation, so getting the group exactly right matters
# less than reporting the path at all; these are for readability of the record.
_TEST_MARKERS = ("test_", "_test.", ".test.", ".spec.", "/tests/", "/test/", "__tests__")
_CONFIG_SUFFIXES = (
    ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml", ".conf", ".env", ".lock",
)
_CONFIG_NAMES = {"Makefile", "Dockerfile", ".coveragerc", ".gitignore"}


def git(repo, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=repo, capture_output=True, text=True
    )


def files_in_commit(repo, commit):
    """Every path the commit changed. Returns (paths, problem)."""
    completed = git(repo, "show", "--name-only", "--format=", "--no-renames", commit)
    if completed.returncode != 0:
        return [], (
            f"`git show {commit}` failed: {completed.stderr.strip()}. The item's footprint "
            "could not be measured, which is reported rather than guessed at (R-10.2)."
        )
    paths = [line.strip() for line in completed.stdout.split("\n") if line.strip()]
    return sorted(set(paths)), None


def classify(path, declared):
    """Which footprint group a path belongs to.

    The declared footprint wins where it names the path, so that a file the plan called
    configuration is compared as configuration. Only a path nothing declared is inferred, and
    such a path is a footprint violation whatever group it lands in.
    """
    for group in ("production", "test", "config"):
        if path in declared.get(group, set()):
            return group
    lowered = path.lower()
    if any(marker in lowered for marker in _TEST_MARKERS):
        return "test"
    base = os.path.basename(path)
    if base in _CONFIG_NAMES or any(base.endswith(s) for s in _CONFIG_SUFFIXES):
        return "config"
    return "production"


def declared_footprint(node):
    footprint = node.get("files-touched") or {}
    return {
        group: {p for p in (footprint.get(group) or []) if isinstance(p, str)}
        for group in ("production", "test", "config")
    }


def measure(plan, item_id, repo, commit, exclude=()):
    """The footprint the item actually left, and how it differs from the declared one."""
    node = plan.node("work-item", item_id).node
    declared = declared_footprint(node)
    declared_all = set().union(*declared.values())

    paths, problem = files_in_commit(repo, commit)
    excluded = [p for p in paths if any(
        p == e or p.startswith(e.rstrip("/") + "/") for e in exclude
    )]
    paths = [p for p in paths if p not in excluded]

    grouped = {"production": [], "test": [], "config": []}
    for path in paths:
        grouped[classify(path, declared)].append(path)
    for group in grouped:
        grouped[group].sort()

    actual_all = set(paths)
    return {
        "files_touched": grouped,
        "declared_only": sorted(declared_all - actual_all),
        "actual_only": sorted(actual_all - declared_all),
        "excluded_from_measurement": excluded,
        "problem": problem,
    }


def verdict(measurement):
    """Whether the footprint holds, and what to do when it does not.

    A file touched that nothing declared is a **failure of the item** under R-2.2, not a
    prompt to edit the plan. A declared file left untouched is not a failure at all: an item
    may perfectly well finish without needing everything the planner listed, and that
    difference is information for the report rather than a fault.
    """
    if measurement["problem"]:
        return "unknown", measurement["problem"]
    if measurement["actual_only"]:
        return "exceeded", (
            f"{len(measurement['actual_only'])} file(s) were touched that this item's "
            "footprint does not declare: " + ", ".join(measurement["actual_only"])
            + ". R-2.2: the item fails with an explanation of what was needed and why. Do not "
            "widen `files-touched` to match — it is planner content, and rewriting it would "
            "destroy the one measurement that could ever justify running slices concurrently."
        )
    if measurement["declared_only"]:
        return "narrower", (
            f"{len(measurement['declared_only'])} declared file(s) were not touched: "
            + ", ".join(measurement["declared_only"])
            + ". Not a failure — an item may finish without needing everything the planner "
            "listed — but the report says so, because a footprint that is routinely too wide "
            "is a planning signal."
        )
    return "exact", "the declared footprint and the actual one are the same set."


def build(plan, item_id, repo, commit, checks, attempts, started, finished, exclude=()):
    """The `actuals` mapping, ready for the writer."""
    measurement = measure(plan, item_id, repo, commit, exclude)
    actuals = {
        "attempts": attempts,
        "files_touched": measurement["files_touched"],
        "checks": checks,
    }
    if started:
        actuals["started"] = started
    if finished:
        actuals["finished"] = finished
    return actuals, measurement


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--item", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--commit", default="HEAD",
                        help="the commit the item's work landed in")
    parser.add_argument("--checks", help="the check runner's JSON output")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--started")
    parser.add_argument("--finished")
    parser.add_argument("--exclude", nargs="*", default=[],
                        help="paths to leave out of the measurement, such as the plan file "
                             "and the sidecar log, which the run writes for its own record "
                             "rather than as part of any item's work")
    parser.add_argument("--footprint-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    plan = planio.Plan(args.plan, phase="executed", lint_writes=False)

    checks = []
    if args.checks:
        with open(args.checks, encoding="utf-8") as handle:
            payload = json.load(handle)
        checks = payload.get("checks", payload) if isinstance(payload, dict) else payload
        # The recorded shape carries only what the schema knows; the runner's extra fields
        # (file, metric, before, after) are useful for the run summary and are dropped here so
        # the writeback lints.
        allowed = {"kind", "outcome", "claim", "detail", "log"}
        checks = [{k: v for k, v in c.items() if k in allowed} for c in checks]

    exclude = list(args.exclude) or [args.plan, "docs/test-execution-log"]

    if args.footprint_only:
        measurement = measure(plan, args.item, args.repo, args.commit, exclude)
        state, note = verdict(measurement)
        payload = {"item": args.item, "commit": args.commit, "verdict": state,
                   "note": note, **measurement}
    else:
        actuals, measurement = build(
            plan, args.item, args.repo, args.commit, checks, args.attempts,
            args.started, args.finished, exclude,
        )
        state, note = verdict(measurement)
        payload = {"item": args.item, "commit": args.commit, "verdict": state, "note": note,
                   "actuals": actuals,
                   "declared_only": measurement["declared_only"],
                   "actual_only": measurement["actual_only"]}

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"{args.item} at {args.commit}: footprint {payload['verdict']}")
        print(f"  {payload['note']}")
        for group, paths in (payload.get("actuals", payload)["files_touched"]).items():
            if paths:
                print(f"  {group}: " + ", ".join(paths))
    return 0 if payload["verdict"] in ("exact", "narrower") else 1


if __name__ == "__main__":
    sys.exit(main())

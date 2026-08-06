#!/usr/bin/env python3
"""The machine-readable run summary stage four consumes without re-parsing the plan (R-9.3).

Items by final status, claims by final state, defects, disputes, coverage before and after,
footprint diffs, inherited failures, and every way the run narrowed its own scope.

**It is derived, never authored.** Every figure comes from the plan, the pre-flight record,
the coverage baseline, or git — and the stage two linter recomputes the item, defect, and
dispute lists and fails the plan on a disagreement. That check exists because a summary is
believed: it is what stage four reads, and a summary that drifted from a late status change
would misreport the run with nothing to catch it.

**`narrowings` is the part worth writing carefully.** R-10.3 says a partial run that reports
honestly is a success mode and only silent omission is failure. Each entry says what was
narrowed *and what the narrowing cost*, in the same shape planning R-13.3 asks of inherited
degradations — because "three items were skipped" is a fact and "ledger/io.py is untouched,
so C8 and C9 remain pinned rather than asserted" is a report.

Usage:
    python3 run_summary.py <plan> --repo . --write        # append or replace the block
    python3 run_summary.py <plan> --repo . --json         # print it, change nothing
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_runner  # noqa: E402
import planio  # noqa: E402
import siblings  # noqa: E402

planlib = siblings.planlib()

DEFAULT_LOG_DIR = "docs/test-execution-log"

SUMMARY_INTRO = """\
Machine-readable, so stage four can report on this run without re-parsing the plan (R-9.3).
Derived from the sections above rather than authored beside them: the stage two linter
recomputes the item, defect, and dispute lists and fails on a disagreement."""

# What each terminal status costs, phrased for a reader deciding what to do next rather than
# for one auditing the run. These are the sentences the narrowings are built from.
_STATUS_COST = {
    "skipped": (
        "not attempted, because the decision blocking it went unanswered. Answering it makes "
        "this work executable in a further run and costs nothing else"
    ),
    "stale": (
        "not attempted, because the target moved between planning and this run. It needs "
        "re-planning against the code as it now stands, not retargeting by the executor"
    ),
    "blocked-by-failure": (
        "never reached, because something it depends on did not complete. It becomes "
        "executable again as soon as that does"
    ),
    "failed": (
        "attempted and not completed. The diagnosis on each says what was tried and what the "
        "check runner reported; a failure here means the plan asked for something that turned "
        "out not to work, which is more interesting than an item nobody attempted"
    ),
    "in-progress": (
        "left unfinished. The run did not reach a terminal status for it, so nothing here "
        "reports on whether the work was any good"
    ),
    "pending": (
        "never started. The run ended before reaching it"
    ),
    "blocked-on-decision": (
        "never started, and still carrying the blocker the planner gave it"
    ),
}


def git(repo, *arguments):
    return subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True)


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def collect(plan, repo, log_dir):
    preflight = load_json(os.path.join(repo, log_dir, "preflight.json")) or {}
    baseline = check_runner.load_baseline(repo, log_dir)

    by_status = {}
    for item_id, block in plan.items.items():
        status = block.node.get("status")
        if isinstance(status, str):
            by_status.setdefault(status, []).append(item_id)
    for ids in by_status.values():
        ids.sort(key=plan._item_key)

    by_label = {}
    for claim_id, block in plan.claims.items():
        label = block.node.get("label")
        if isinstance(label, str):
            by_label.setdefault(label, []).append(claim_id)
    for ids in by_label.values():
        ids.sort(key=lambda c: int(c[1:]) if c[1:].isdigit() else 10**9)

    summary = {
        "summary_version": "1.0",
        "branch": (preflight.get("branch") or {}).get("branch")
        or git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
        "base_commit": preflight.get("base_commit"),
        "items": [
            {"status": status, "count": len(ids), "ids": ids}
            for status, ids in sorted(by_status.items())
        ],
        "claims": [
            {"label": label, "count": len(ids), "ids": ids}
            for label, ids in sorted(by_label.items())
        ],
        "defects": sorted(plan.defects),
        "disputes": sorted(
            (c for c, b in plan.claims.items() if b.node.get("label") == "disputed"),
            key=lambda c: int(c[1:]) if c[1:].isdigit() else 10**9,
        ),
        "coverage": coverage_rows(plan, repo, log_dir, baseline),
        "footprint": footprint_rows(plan),
        "inherited_failures": list(
            (preflight.get("baseline") or {}).get("inherited_failures") or []
        ),
    }
    for key in ("started", "finished"):
        value = preflight.get("baseline", {}).get(key) or preflight.get(key)
        if isinstance(value, str):
            summary[key] = value
    summary["narrowings"] = narrowings(plan, summary, preflight, by_status)
    return summary


def coverage_rows(plan, repo, log_dir, baseline):
    """Every declared coverage delta, with what it started at and what it reached.

    `after` is null where the item never ran, and that is a different fact from a figure of
    zero. Recording it as zero would say the tests reached nothing, when what happened is that
    nobody measured.
    """
    measured = {}
    command, report = check_runner.coverage_source(plan)
    full = os.path.join(repo, report) if report else None
    if full and os.path.exists(full):
        parsed, problem = None, None
        try:
            from pathlib import Path  # noqa: PLC0415

            parse = siblings.parse_coverage()
            fmt = parse.sniff(Path(full))
            if fmt != "unknown":
                parsed = parse.PARSERS[fmt](Path(full))
        except Exception:  # noqa: BLE001 — an unreadable report leaves `after` null
            parsed = None
        if parsed is not None:
            measured = parsed

    rows = []
    for item_id in sorted(plan.items, key=plan._item_key):
        node = plan.items[item_id].node
        ran = node.get("status") in ("done", "done-with-defect")
        for delta in node.get("coverage-delta") or []:
            if not isinstance(delta, dict):
                continue
            path, metric = delta.get("file"), delta.get("metric")
            after = (
                check_runner._file_metric(measured, path, metric)
                if (measured and ran) else None
            )
            before = baseline.get(f"{path}:{metric}")
            if before is None:
                before = delta.get("from")
            row = {
                "file": path,
                "metric": metric,
                "before": round(float(before), 2) if isinstance(before, (int, float)) else 0.0,
                "after": round(after, 2) if isinstance(after, (int, float)) else None,
                "target": delta.get("to"),
                "met": bool(
                    isinstance(after, (int, float))
                    and isinstance(delta.get("to"), (int, float))
                    and after >= delta["to"]
                ),
            }
            rows.append(row)
    return rows


def footprint_rows(plan):
    """Declared against actual, per item, which is the measurement R-10.3 gates on."""
    rows = []
    for item_id in sorted(plan.items, key=plan._item_key):
        node = plan.items[item_id].node
        actuals = node.get("actuals")
        if not isinstance(actuals, dict):
            continue
        declared = set()
        for group in ("production", "test", "config"):
            declared |= {
                p for p in ((node.get("files-touched") or {}).get(group) or [])
                if isinstance(p, str)
            }
        actual = set()
        for group in ("production", "test", "config"):
            actual |= {
                p for p in ((actuals.get("files_touched") or {}).get(group) or [])
                if isinstance(p, str)
            }
        rows.append({
            "item": item_id,
            "declared_only": sorted(declared - actual),
            "actual_only": sorted(actual - declared),
        })
    return rows


def narrowings(plan, summary, preflight, by_status):
    """Every way the run's scope ended up smaller than the plan's, and what each cost."""
    out = list(preflight.get("narrowings") or [])
    seen = {entry.get("what") for entry in out if isinstance(entry, dict)}

    for status in ("stale", "skipped", "blocked-by-failure", "failed", "in-progress",
                   "pending", "blocked-on-decision"):
        ids = by_status.get(status) or []
        if not ids:
            continue
        what = f"{len(ids)} item(s) ended `{status}`"
        if what in seen:
            continue
        claims = sorted(
            {
                claim
                for item_id in ids
                for claim in (plan.items[item_id].node.get("claims") or [])
                if isinstance(claim, str)
            },
            key=lambda c: int(c[1:]) if c[1:].isdigit() else 10**9,
        )
        cost = f"{', '.join(ids)} — " + _STATUS_COST.get(status, "not completed")
        if claims:
            cost += (
                f". The claim(s) {', '.join(claims)} are therefore asserted by no test in "
                "this run and stay as the planner labelled them."
            )
        out.append({"what": what, "cost": cost + "."})

    unmet = [row for row in summary["coverage"] if not row["met"]]
    if unmet:
        out.append({
            "what": f"{len(unmet)} declared coverage delta(s) were not met",
            "cost": "; ".join(
                f"{row['file']} {row['metric']} reached "
                + (f"{row['after']}%" if row["after"] is not None else "no measurement")
                + f" against a target of {row['target']}%"
                for row in unmet[:8]
            ) + ". A delta with no measurement is an item that never ran, which is a "
                "different fact from a target that was missed.",
        })

    exceeded = [row for row in summary["footprint"] if row["actual_only"]]
    if exceeded:
        out.append({
            "what": f"{len(exceeded)} item(s) touched files outside their declared footprint",
            "cost": "; ".join(
                f"{row['item']}: {', '.join(row['actual_only'])}" for row in exceeded[:8]
            ) + ". R-2.2 makes this an item failure rather than a footprint widening, and "
                "planning R-10.3 gates concurrent execution on the two agreeing — so every "
                "entry here is a reason not to enable it yet.",
        })

    if summary["defects"]:
        out.append({
            "what": f"{len(summary['defects'])} defect(s) are standing red",
            "cost": (
                f"{', '.join(summary['defects'])}. The suite is not green and is not meant to "
                "be: each red test blocks the pipeline until the owner makes a recorded "
                "decision about the defect, which is the point rather than a side effect. The "
                "run is not closed until each carries an answer (R-7.6)."
            ),
        })
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--assessment")
    parser.add_argument("--narrowing", nargs=2, action="append", default=[],
                        metavar=("WHAT", "COST"),
                        help="an observed narrowing the scripts cannot compute — inherited "
                             "lint failures, a generated directory nothing ignores, an "
                             "estimate the run turned out to contradict. R-10.3 requires "
                             "every narrowing and its cost, and the derived ones are only "
                             "the ones a script can see")
    parser.add_argument("--write", action="store_true",
                        help="write the block into the plan and a JSON copy to the sidecar")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    plan = planio.Plan(args.plan, assessment=args.assessment, phase="executed",
                       lint_writes=args.write)
    summary = collect(plan, args.repo, args.log_dir)
    # Observed narrowings go after the derived ones. The derived parts stay derived — the
    # linter recomputes the item, defect, and dispute lists — and these are the executor's
    # judgment, in the same category as a diagnosis.
    summary["narrowings"].extend(
        {"what": what, "cost": cost} for what, cost in args.narrowing
    )

    if args.write:
        try:
            changed = plan.upsert_block(
                planio.SUMMARY_SECTION, "run-summary", summary, {}, intro=SUMMARY_INTRO,
            )
        except planio.WriteRejected as rejected:
            print(str(rejected), file=sys.stderr)
            return 1
        os.makedirs(os.path.join(args.repo, args.log_dir), exist_ok=True)
        target = os.path.join(args.repo, args.log_dir, "run-summary.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
        print(f"{'wrote' if changed else 'unchanged'}: the run summary in {args.plan}")
        print(f"  and a copy at {os.path.join(args.log_dir, 'run-summary.json')}")

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif not args.write:
        print(f"{args.plan} — run summary")
        for entry in summary["items"]:
            print(f"  {entry['status']:20} {entry['count']:3}  {', '.join(entry['ids'])}")
        print(f"  defects: {', '.join(summary['defects']) or 'none'}")
        print(f"  disputes: {', '.join(summary['disputes']) or 'none'}")
        print(f"  inherited failures: {len(summary['inherited_failures'])}")
        for entry in summary["narrowings"]:
            print(f"  narrowing: {entry['what']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

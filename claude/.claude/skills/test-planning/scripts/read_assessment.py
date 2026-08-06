#!/usr/bin/env python3
"""Extract and validate the assessment index. Hard-stops when there is none.

This is step one of the planning procedure and the only place stage two reads the
assessment mechanically. Everything downstream — the value line, the partition, the
completeness rule in the linter — works from what this returns.

**When the report carries no index, this fails and prints the backfill instruction.** It
does not degrade. Stage one's rule is "degrade, do not fail", and that rule is about
deficiencies in the *target repository*: a missing suite, absent requirements, unavailable
tooling. It is not about stage two's own input contract. A plan built by guessing at an
unindexed report would carry references that resolve to nothing, and the linter's
completeness rule — the one thing standing between the plan and a silently dropped top-tier
finding — would have no finding list to check against. Degrading here means producing a plan
that looks complete and is not.

Usage:
    python3 read_assessment.py docs/test-assessment.md
    python3 read_assessment.py docs/test-assessment.md --json
    python3 read_assessment.py docs/test-assessment.md --value-line high --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planlib  # noqa: E402

INDEX_INFO_STRING = "json assessment-index"
TIER_ORDER = ["top", "high", "medium", "low"]

# Schema versions this planner understands. 1.1 added the function-granularity testability
# section; 1.0 is otherwise identical and is accepted here so that it can be routed to the
# narrow backfill below rather than refused as unreadable. The two situations have different
# remedies and telling the owner to re-run an assessment that only needs topping up wastes a
# verification pass.
#
# 1.2 added the `reconciliation` array, which this planner does not read: its own obligation
# to the run ledger is Step 9b, which queries `ledger.py --open` directly rather than trusting
# the assessment's account of what is open. So 1.2 is accepted with nothing else changed.
#
# **This list was one version behind `check_index.py` for the whole of 1.2's life, and the two
# together made the stage one to stage two interface impassable**: the checker rejected any
# index below 1.2 and this planner rejected any index at it, so no report could satisfy both.
# It surfaced when the pipeline orchestrator ran both validators against one report for the
# first time, which is the general shape worth noting — a version constant duplicated across
# two skills has no check standing over the pair, and each is individually correct while the
# interface between them is broken. Adding the orchestrator is what made anything run them
# together.
SUPPORTED_VERSIONS = ("1.0", "1.1", "1.2")
CURRENT_VERSION = "1.2"

BACKFILL_INSTRUCTION = """\
The assessment report at {path} has no machine-readable index, so stage two cannot read it.

This is a hard stop, not a degradation. Planning R-4.4 requires stable identifiers on
findings, recommendations, and exclusions so that a work item can reference one and have the
reference survive a correction. Positional numbering does not survive: stage one's
verification pass corrected nineteen claims in one real run, and any correction that merges
or splits a finding renumbers everything below it.

To fix it, run the assessment skill in backfill mode against this report:

    Use the test-assessment skill in backfill mode on {path}

Backfill mode does only Step 9b of that skill's procedure. It assigns identifiers to what the
report already says, adds the ID column to the findings, exclusions, and degradations tables,
writes the index, and validates it with check_index.py. It re-measures nothing and re-derives
nothing, because the report has already been through its verification pass and re-running the
analysis would produce a report that pass never saw.

Then run this script again.
"""

TESTABILITY_BACKFILL_INSTRUCTION = """\
The assessment index at {path} carries no function-granularity testability section, so
stage two cannot check that the claims it plans are actually assertable.

{detail}

This is a hard stop, not a degradation, for the same reason a missing index is: it is a
deficiency in stage two's own input contract rather than in the target repository. Planning
R-11.4 requires every claim an item asserts to be assertable by the time that item runs, and
it decides that by resolving the claim's location against this section. Without it the
planner can only assume every target is reachable — which is how a plan comes to assert
claims through an extraction that no work item performs, and to assert a claim in an early
slice while the seam enabling it sits in the last one. Both defects have been produced by
this planner in practice.

To fix it, run the assessment skill in backfill mode against this report:

    Use the test-assessment skill in backfill mode on {path}

Backfill mode re-measures nothing. For this section it runs Step 6 of that skill's
procedure: it takes the function enumeration from complexity.py, classifies the bounded set
(every function in the top and high tiers, plus every function named in a recommendation's
locations), writes Section 8's proportions from those entries, adds `testability` and
`testability_scope` to the index, sets `index_version` to {version}, and validates the whole
block with check_index.py.

Then run this script again.
"""


class AssessmentError(Exception):
    def __init__(self, message, instruction=None):
        super().__init__(message)
        self.message = message
        self.instruction = instruction


def read_index(path):
    """Return the parsed index. Raises AssessmentError with an instruction on failure."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as error:
        raise AssessmentError(
            f"cannot read the assessment report at {path}: {error}",
            "Check the path. The planner is given the assessment's recorded location and "
            "does not search for it.",
        ) from error

    blocks = [b for b in planlib.extract_blocks(text) if b.info.strip() == INDEX_INFO_STRING]

    if not blocks:
        raise AssessmentError(
            f"{path} contains no `{INDEX_INFO_STRING}` block",
            BACKFILL_INSTRUCTION.format(path=path),
        )
    if len(blocks) > 1:
        raise AssessmentError(
            f"{path} contains {len(blocks)} index blocks (lines "
            + ", ".join(str(b.fence_line) for b in blocks)
            + "); exactly one is permitted",
            "Two indexes cannot both be authoritative. Delete the stale one and re-validate "
            "with check_index.py.",
        )

    block = blocks[0]
    try:
        index = json.loads(block.body)
    except json.JSONDecodeError as error:
        raise AssessmentError(
            f"{path}:{block.body_start_line + error.lineno - 1}: the index is not valid "
            f"JSON: {error.msg}",
            "Fix the block and re-validate it with the assessment skill's check_index.py "
            "before planning against it.",
        ) from error

    if not isinstance(index, dict):
        raise AssessmentError(f"{path}: the index must be a JSON object")

    version = index.get("index_version")
    if version not in SUPPORTED_VERSIONS:
        raise AssessmentError(
            f"{path}: index_version is {version!r}, and this planner understands "
            + " and ".join(SUPPORTED_VERSIONS)
            + " only",
            "A planner that guesses at an unrecognised schema version produces references "
            "that may not mean what it thinks. Update the skill or re-emit the index.",
        )

    check_testability_present(path, index, version)
    return index


def check_testability_present(path, index, version):
    """Hard-stop with the narrow backfill instruction when the testability section is absent.

    Three cases reach this, and they are one problem: a 1.0 index, which predates the
    section; a 1.1 index missing it; and a 1.1 index whose section is the wrong shape. All
    three leave R-11.4 with nothing to check, and all three are fixed by the same bounded
    piece of work rather than by re-running the assessment.

    An *empty* testability list is not one of them. A report may legitimately classify
    nothing — it has no findings above the value line, say. The per-claim check in the
    linter is what catches a claim that cannot resolve, and it names the exact function to
    classify, which is a far more useful failure than a blanket stop here would be.
    """
    if version == "1.0":
        raise AssessmentError(
            f"{path}: the index is at schema version 1.0, which predates the testability "
            "section",
            TESTABILITY_BACKFILL_INSTRUCTION.format(
                path=path,
                version=CURRENT_VERSION,
                detail=(
                    "The index is well-formed. Version 1.0 is this same schema without "
                    "`testability` and `testability_scope`, so nothing here is wrong — it "
                    "was written before the section existed and needs topping up, not "
                    "re-deriving."
                ),
            ),
        )

    missing = [
        key
        for key, kind in (("testability", list), ("testability_scope", dict))
        if not isinstance(index.get(key), kind)
    ]
    if missing:
        raise AssessmentError(
            f"{path}: the index is at version {version} but "
            + " and ".join(f"`{key}`" for key in missing)
            + (" is" if len(missing) == 1 else " are")
            + " absent or malformed",
            TESTABILITY_BACKFILL_INSTRUCTION.format(
                path=path,
                version=CURRENT_VERSION,
                detail=(
                    "The index claims version "
                    f"{version}, which requires "
                    + " and ".join(f"`{key}`" for key in missing)
                    + ". Run check_index.py against the report to see every field it is "
                    "missing before backfilling, rather than adding these two blind."
                ),
            ),
        )


def summarize(index, value_line=None):
    """Everything the planning procedure needs from the index, in one structure."""
    findings = [f for f in index.get("findings", []) if isinstance(f, dict)]
    recommendations = [r for r in index.get("recommendations", []) if isinstance(r, dict)]

    if value_line is None:
        value_line = suggest_value_line(findings)
    cutoff = TIER_ORDER.index(value_line) if value_line in TIER_ORDER else len(TIER_ORDER)

    def above(entry):
        tier = entry.get("tier")
        return tier in TIER_ORDER and TIER_ORDER.index(tier) <= cutoff

    contested = [
        {"id": entry["id"], "section": section, "contested": entry["contested"]}
        for section in ("findings", "recommendations", "exclusions")
        for entry in index.get(section, []) or []
        if isinstance(entry, dict) and entry.get("contested")
    ]

    unsafe = [r["id"] for r in recommendations if r.get("safe_to_execute") is False]
    estimated = [m["name"] for m in index.get("metrics", []) or []
                 if isinstance(m, dict) and m.get("basis") == "estimated"]

    baseline = index.get("coverage_baseline") or {}

    return {
        "repository": index.get("repository"),
        "mode": index.get("mode"),
        "verification": index.get("verification"),
        "commit": index.get("commit"),
        "value_line": value_line,
        "findings_above_line": [f["id"] for f in findings if above(f)],
        "findings_below_line": [f["id"] for f in findings if not above(f)],
        "tier_counts": {
            tier: sum(1 for f in findings if f.get("tier") == tier) for tier in TIER_ORDER
        },
        "contested": contested,
        "recommendations_not_safe_to_execute": unsafe,
        "independent_recommendations": [
            r["id"] for r in recommendations if r.get("independent") is True
        ],
        "open_questions": [q["id"] for q in index.get("open_questions", []) or []
                           if isinstance(q, dict)],
        "degradations": [
            {"id": d.get("id"), "degradation": d.get("degradation"), "effect": d.get("effect")}
            for d in index.get("degradations", []) or []
            if isinstance(d, dict)
        ],
        "coverage_baseline_available": bool(baseline.get("available")),
        "coverage_baseline_complete": bool(baseline.get("files_complete")),
        "estimated_metrics": estimated,
        "testability_scope": index.get("testability_scope") or {},
        "testability_counts": testability_counts(index),
        "warnings": build_warnings(index, contested, unsafe, estimated, baseline),
        "index": index,
    }


def testability_counts(index):
    """How many functions fall in each testability category, for the planner's summary."""
    counts = {}
    for entry in index.get("testability") or []:
        if isinstance(entry, dict) and isinstance(entry.get("category"), str):
            counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    return counts


def suggest_value_line(findings):
    """Suggest the lowest tier worth planning for. The planner may override it.

    The default is `high`: the top two tiers are what the risk ranking exists to surface.
    When there are no findings above `medium`, the suggestion drops to whatever the lowest
    populated tier is, because a value line above every finding would plan for nothing.
    """
    populated = [t for t in TIER_ORDER if any(f.get("tier") == t for f in findings)]
    if not populated:
        return "high"
    default_cutoff = TIER_ORDER.index("high")
    lowest_populated = TIER_ORDER.index(populated[-1])
    return TIER_ORDER[min(default_cutoff, lowest_populated)] if lowest_populated > default_cutoff \
        else TIER_ORDER[lowest_populated]


def build_warnings(index, contested, unsafe, estimated, baseline):
    """Things the planner must act on, phrased as what to do rather than what is wrong."""
    warnings = []
    if contested:
        warnings.append(
            "Contested: " + ", ".join(c["id"] for c in contested) + ". R-4.3 forbids "
            "building a work item on any of these as they stand. Resolve each by reading "
            "the evidence and record the resolution in the plan's `assessment_resolutions`, "
            "or escalate it as a decision."
        )
    if unsafe:
        warnings.append(
            "Not safe to execute as written: " + ", ".join(unsafe) + ". The assessment says "
            "so; scheduling one anyway means overriding a judgment stage one already made. "
            "Escalate instead."
        )
    if index.get("verification") == "skipped":
        warnings.append(
            "The assessment's verification pass was skipped, so every finding here is "
            "single-sourced. Record this as an inherited degradation and say what it costs "
            "the plan's confidence."
        )
    if estimated:
        warnings.append(
            "Estimated rather than measured: " + ", ".join(estimated) + ". A target derived "
            "from an estimate must say so, or it is a target nobody can be held to."
        )
    if baseline.get("available") and not baseline.get("files_complete"):
        warnings.append(
            "The per-file coverage baseline is incomplete: the assessment named only some "
            "instrumented files. A file it did not name has no recorded baseline, so a "
            "`coverage-delta` check on it must use `baseline-source: slice-zero` rather "
            "than assuming zero."
        )
    if not baseline.get("available"):
        warnings.append(
            "There is no coverage baseline. Every `coverage-delta` check starts from zero "
            "by construction, and the target must be stated against the denominator slice "
            "zero establishes."
        )
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("assessment", help="path to the assessment report")
    parser.add_argument("--value-line", choices=TIER_ORDER, help="override the suggested value line")
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    parser.add_argument("--full-index", action="store_true", help="with --json, include the whole index")
    args = parser.parse_args()

    try:
        index = read_index(args.assessment)
    except AssessmentError as error:
        print(f"STOP: {error.message}\n", file=sys.stderr)
        if error.instruction:
            print(error.instruction, file=sys.stderr)
        return 2

    summary = summarize(index, args.value_line)
    if not args.full_index:
        summary.pop("index", None)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    print(f"{summary['repository']} — assessment read from {args.assessment}")
    print(f"  mode {summary['mode']}, verification {summary['verification']}, commit {summary['commit']}")
    print(f"  tiers: " + ", ".join(f"{t} {n}" for t, n in summary["tier_counts"].items() if n))
    print(f"  value line suggested at `{summary['value_line']}`")
    print(f"  above the line: {', '.join(summary['findings_above_line']) or 'none'}")
    print(f"  below the line: {', '.join(summary['findings_below_line']) or 'none'}")
    print(f"  open questions: {', '.join(summary['open_questions']) or 'none'}")
    scope = summary["testability_scope"]
    counts = summary["testability_counts"]
    print(
        "  testability: "
        + (", ".join(f"{category} {n}" for category, n in sorted(counts.items())) or "none")
        + f" (tiers {', '.join(scope.get('tiers') or []) or 'none'}, "
        + ("complete" if scope.get("complete") else "bounded set")
        + ")"
    )
    print(f"  degradations to inherit: {', '.join(d['id'] for d in summary['degradations']) or 'none'}")
    if summary["warnings"]:
        print("\n  Act on these before building work items:")
        for warning in summary["warnings"]:
            print(f"    - {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

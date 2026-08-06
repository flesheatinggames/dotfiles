#!/usr/bin/env python3
"""Write docs/test-report.md: every table filled from the run record, every prose slot marked.

R-5.1 read literally. Deterministic scripts assemble the run record and every table and figure
in the narrative report; the model writes only prose around numbers it did not compute.

**The tables are pre-filled rather than merely policed, and that is the design.**
`trace_report.py` can prove that a number in the prose came from the record, but a checker
that fires often is a checker that gets disabled — so the arrangement here is that a prose
number should be *rare by construction*. Everything countable is already in a table above the
paragraph that discusses it, and the writer's job is to say what the tables mean rather than to
restate them.

**The report is one per run and the next run overwrites it.** The run ledger is what survives
across runs; each ledger run entry records the commit its report was written in, so an old
report is retrievable from history. This matches how stages one and two treat their own
outputs, and it avoids a directory of reports that disagree about which is current.

Usage:
    python3 assemble.py docs/test-plan.md --repo .
    python3 assemble.py docs/test-plan.md --repo . --out docs/test-report.md
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger as ledger_module  # noqa: E402
import run_record  # noqa: E402
import siblings  # noqa: E402

planlib = siblings.planlib()

# The prose slots, in the order they appear. Each is a named region the model fills and the
# tracer checks. The brief for each names the reference that governs it, because a slot with no
# standard behind it gets filled with whatever the writer had to hand.
PROSE_SLOTS = (
    (
        "executive-layer",
        "The plain-language executive layer (R-5.3). Three to six short paragraphs, readable "
        "by someone who was never part of this pipeline's design: what was verified, what was "
        "not, and what was found. No pipeline vocabulary without an inline definition — "
        "'claim', 'mutation check', 'seam', 'slice', 'pinned' all need one. State every "
        "number from the tables in this document and none from anywhere else. See "
        "references/plain-language-brief.md, and run the fresh-context reader it describes.",
    ),
    (
        "asserted-behavior",
        "What the accounting above means. Which behaviors the suite would now notice breaking, "
        "and which it merely executes. Do not restate the table; say what a reader should "
        "conclude from it.",
    ),
    (
        "undelivered-scope",
        "What is missing and why it matters, item by item where the reasons differ. R-5.5: "
        "never netted away. A run that delivered most of its plan says which part it did not "
        "and what that leaves unverified.",
    ),
    (
        "inheritance",
        "What this run inherited and did not change: failures that were already red, "
        "exclusions carried from the assessment, and every way the run narrowed its own scope. "
        "Each with what it costs the conclusions below.",
    ),
    (
        "decisions",
        "The defects, the owner's answers, and what each answer did to the branch. Where a "
        "defect is still open, say what a reader should do about it and what happens if they "
        "do nothing.",
    ),
    (
        "disputes",
        "What the disputes say about the planning that produced them, and what the next plan "
        "should start from instead. A dispute is a planner error with nothing red on the "
        "branch, so this section is about future work rather than about risk.",
    ),
    (
        "footprint",
        "What the declared-versus-actual diff says. Planning R-10.3 gates concurrent execution "
        "on these agreeing across real plans; state what this run contributes to that "
        "question.",
    ),
    (
        "pipeline-findings",
        "What this run learned about the pipeline rather than about the repository. Recurring "
        "findings first; R-8.2 flags them because a problem the pipeline keeps producing is "
        "the raw material for a requirements amendment.",
    ),
    (
        "trust-statement",
        "The trust statement (R-5.6). Read references/trust-statement.md before writing it. "
        "Every positive claim cites its evidence class; unknowns and exclusions stand beside "
        "what is known; no scalar grade, score, or letter appears anywhere; and the statement "
        "carries its date and its commit, because trust decays as the code changes under a "
        "static suite.",
    ),
)

_AUTHORITY_MEANING = {
    "cited": "a requirements document says so, quoted inline in the plan",
    "ratified": "the owner personally confirmed this is intended behavior",
    "ratified-as-observed": "the owner ruled the specification wrong and accepted what the "
                            "code does",
    "pinned": "read from the code; nobody has confirmed it is intended",
    "disputed": "a faithful test contradicted the planner's reading; asserts nothing",
}

# Which side of R-5.4's specified-versus-pinned split each authority falls on. The split is
# stated in the report rather than assumed, because `ratified-as-observed` is the one that
# could reasonably go either way and the report's central distinction rests on the answer:
# the owner ratified it, but what they ratified is what the code already did.
SPECIFIED = ("cited", "ratified")
OBSERVED = ("pinned", "ratified-as-observed")


_SLOT_RE = re.compile(
    r"<!-- PROSE (?P<name>[\w-]+) —.*?-->\n(?P<body>.*?)<!-- END PROSE (?P=name) -->",
    re.DOTALL,
)


def existing_prose(path):
    """The prose already written into a report, so re-assembling does not destroy it.

    The record moves after a report is written more often than it sounds: the close-out gate
    appends to the ledger, the findings are classified, a consistency check's wording is
    corrected. Each of those changes the skeleton, and `trace_report.py` correctly refuses a
    report whose generated regions no longer match a fresh assembly.

    Without this, the only remedy would be to re-assemble and write every slot again — which
    makes the tracer punishing rather than useful, and a tool that punishes correct behavior is
    one people route around. The prose is the author's; only the skeleton is regenerated.
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return {
        match.group("name"): match.group("body")
        for match in _SLOT_RE.finditer(text)
        if match.group("body").strip() and "**To write:**" not in match.group("body")
    }


def prose_slot(name, brief, written=None):
    body = written.get(name) if written else None
    return "\n".join([
        f"<!-- PROSE {name} — written by the model, checked by trace_report.py -->",
        body.rstrip("\n") if body else f"> **To write:** {brief}",
        f"<!-- END PROSE {name} -->",
    ])


def cell(value):
    """One table cell: whitespace collapsed and pipes escaped.

    Both matter and neither is cosmetic. The prose this pulls in comes from folded YAML
    scalars, which read back with their line breaks intact — and a line break inside a
    Markdown table cell ends the table there, so a five-row narrowings table renders as one row
    followed by loose text. An unescaped pipe in a quoted command does the same thing sideways,
    splitting one cell into two and shifting every column after it.
    """
    if value is None:
        return ""
    return " ".join(str(value).split()).replace("|", "\\|")


def table(headers, rows, empty="_Nothing to report._"):
    if not rows:
        return empty
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(lines)


def _key(identifier):
    text = identifier or ""
    tail = text.rstrip("0123456789")
    number = text[len(tail):]
    return (tail, int(number) if number else 0)


# --------------------------------------------------------------------------------------
# The per-claim accounting (R-5.4)
# --------------------------------------------------------------------------------------


def claim_rows(record, plan):
    """Every claim with its authority, its asserting tests, and its mutation evidence.

    The mutation evidence is the column that earns the section. A claim with a passing
    assertion and no mutation check is a claim the suite executes; a claim whose mutation check
    passed is one the suite would notice breaking. Reporting them the same way would be the
    report-level version of the vanity coverage number this project exists to kill.
    """
    authority_of = {}
    for entry in record.get("claims") or []:
        for claim_id in entry.get("ids") or []:
            authority_of[claim_id] = entry.get("label")

    asserting = {}
    waivers = {}
    for item_id, block in plan.items.items():
        for check in block.node.get("completion-checks") or []:
            if not isinstance(check, dict) or check.get("kind") != "mutation":
                continue
            claim_id = check.get("claim")
            if isinstance(claim_id, str):
                asserting.setdefault(claim_id, set()).update(
                    name for name in (check.get("tests") or []) if isinstance(name, str)
                )
        for waiver in block.node.get("mutation-waiver") or []:
            if isinstance(waiver, dict) and isinstance(waiver.get("claim"), str):
                waivers[waiver["claim"]] = waiver.get("reason") or ""

    outcomes = {}
    for item_id, block in plan.items.items():
        actuals = block.node.get("actuals")
        if not isinstance(actuals, dict):
            continue
        for check in actuals.get("checks") or []:
            if isinstance(check, dict) and check.get("kind") == "mutation":
                claim_id = check.get("claim")
                if isinstance(claim_id, str):
                    outcomes[claim_id] = check.get("outcome")

    registry = {}
    for defect_id, block in plan.defects.items():
        claim_id = block.node.get("claim")
        if isinstance(claim_id, str):
            registry[claim_id] = defect_id

    rows = []
    for claim_id in sorted(authority_of, key=_key):
        tests = sorted(asserting.get(claim_id) or [])
        outcome = outcomes.get(claim_id)
        if outcome == "passed":
            evidence = "mutation check passed"
        elif outcome == "failed":
            evidence = "mutation check **failed** — the suite did not notice the edit"
        elif outcome == "suspended":
            evidence = f"suspended behind {registry.get(claim_id, 'a registry test')}"
        elif outcome == "not-run":
            evidence = "mutation check could not be run"
        elif claim_id in waivers:
            evidence = "waived: " + waivers[claim_id][:120]
        elif authority_of[claim_id] == "disputed":
            evidence = "none — the claim was impeached"
        else:
            evidence = "no mutation check ran"
        rows.append([
            claim_id,
            authority_of[claim_id],
            ", ".join(f"`{name}`" for name in tests) if tests else "_none recorded_",
            evidence,
        ])
    return rows


def authority_rows(record):
    counts = {
        entry.get("label"): entry.get("count", 0) for entry in record.get("claims") or []
    }
    rows = []
    for label in ("cited", "ratified", "ratified-as-observed", "pinned", "disputed"):
        if label in counts:
            rows.append([label, counts[label], _AUTHORITY_MEANING[label]])
    return rows, counts


# --------------------------------------------------------------------------------------
# The sections
# --------------------------------------------------------------------------------------


def build(record, plan, ledger_data, repository, plan_path, written=None):
    parts = []
    add = parts.append

    add(f"# Test report — {repository}")
    add("")
    add(
        "<!-- Generated by test-reporting/scripts/assemble.py. Every table and figure here is\n"
        "     filled from the run record; nothing in this file was counted by hand (R-5.1).\n"
        "     The prose between PROSE markers is written by the model, and trace_report.py\n"
        "     proves every number in it against the record. A number that fails the trace\n"
        "     fails the assembly. -->"
    )
    add("")
    suite = record.get("final_suite") or {}
    meta_rows = [
        ["Repository", repository],
        ["Plan", f"`{plan_path}`"],
        ["Branch", f"`{record.get('branch')}`"],
        ["Run closed", record.get("closed")],
        ["Closing commit", f"`{run_record.short(record.get('close_commit'))}`"
            if record.get("close_commit") else "_not recorded_"],
        ["Baseline run", record.get("baseline_run") or
            "_none — this is the first closed run against this repository_"],
        ["Commits since the last close-out", record.get("commit_distance")
            if record.get("commit_distance") is not None else "_not applicable_"],
        ["Suite at close-out", _suite_phrase(suite)],
    ]
    add(table(["", ""], meta_rows))
    add("")
    add("---")
    add("")

    add("## 1. In plain language")
    add("")
    add(prose_slot(*PROSE_SLOTS[0], written=written))
    add("")
    add("---")
    add("")

    add("## 2. What the suite now asserts")
    add("")
    rows, counts = authority_rows(record)
    add("Claims by authority — where the statement being tested got its force:")
    add("")
    add(table(["Authority", "Claims", "What the label means"], rows))
    add("")
    specified = sum(counts.get(label, 0) for label in SPECIFIED)
    observed = sum(counts.get(label, 0) for label in OBSERVED)
    disputed = counts.get("disputed", 0)
    add(
        "R-5.4's split. **Specified behavior** is what a document or the owner said must be "
        "true, so a test failure means the code is wrong. **Observed behavior** is what the "
        "code already did, pinned so that a change becomes visible; a test failure there means "
        "something changed, not that something broke. `ratified-as-observed` counts as "
        "observed: the owner ratified it, and what they ratified is what the code was already "
        "doing."
    )
    add("")
    add(table(
        ["Split", "Claims"],
        [
            ["Asserting specified behavior", specified],
            ["Pinning observed behavior", observed],
            ["Impeached, asserting nothing", disputed],
        ],
    ))
    add("")
    add("Per claim, with the evidence each one earned:")
    add("")
    add(table(
        ["Claim", "Authority", "Asserting tests", "Mutation evidence"],
        claim_rows(record, plan),
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[1], written=written))
    add("")
    add("---")
    add("")

    add("## 3. Undelivered scope")
    add("")
    add(
        "R-5.5: itemised by terminal status and never netted away. Each row is work the plan "
        "asked for that this run did not deliver, with the reason recorded at the time."
    )
    add("")
    add(table(
        ["Item", "Status", "Recorded reason"],
        undelivered_rows(record, plan),
        "_Every item in the plan reached a completed status._",
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[2], written=written))
    add("")
    add("---")
    add("")

    add("## 4. What this run inherited and did not change")
    add("")
    add("Failures that were already red before anything ran:")
    add("")
    add(table(
        ["Test"],
        [[f"`{name}`"] for name in record.get("inherited_failures") or []],
        "_The suite had no pre-existing failures at pre-flight._",
    ))
    add("")
    add("Every way the run narrowed its own scope, with what each narrowing cost:")
    add("")
    add(table(
        ["Narrowing", "Cost"],
        [[entry.get("what"), entry.get("cost")]
         for entry in record.get("narrowings") or []],
        "_The run executed its plan without narrowing it._",
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[3], written=written))
    add("")
    add("---")
    add("")

    add("## 5. Defects, decisions, and applied consequences")
    add("")
    if record.get("defects"):
        add(
            "Each row is a place the code contradicted a claim carrying a document's authority "
            "or the owner's. The decision column is the owner's answer at the close-out gate; "
            "nothing here was decided by the pipeline."
        )
    add("")
    add(table(
        ["Defect", "Claim", "Decision", "Decided by", "Consequence commit", "The test now"],
        defect_rows(record, plan),
        "_This run surfaced no defects._",
    ))
    add("")
    if record.get("amendment_flags"):
        add(
            "Documents now known to disagree with accepted behavior (R-6.4). Each is tracked "
            "in the run ledger until it is amended or contested:"
        )
        add("")
        add(table(
            ["Flag", "Document", "Passage"],
            [[flag.get("id"), f"`{flag.get('document')}`", flag.get("passage")]
             for flag in record.get("amendment_flags") or []],
        ))
        add("")
    carried = carried_forward(ledger_data, record)
    if carried:
        add(
            "Carried forward from earlier runs and still open. The next assessment of this "
            "repository is required to confirm, update, or contest every one of them (R-7.2):"
        )
        add("")
        add(table(["Item", "Kind", "Open since", "Summary"], carried))
        add("")
    add(prose_slot(*PROSE_SLOTS[4], written=written))
    add("")
    add("---")
    add("")

    add("## 6. Disputes")
    add("")
    add(
        "A dispute is a claim the planner read out of the code that a faithful test then "
        "contradicted. It impeaches the planner's reading rather than the code, so nothing "
        "stands red on the branch and nothing blocks the merge. R-6.5 makes answering one "
        "optional; an unanswered dispute stays an open ledger item."
    )
    add("")
    add(table(
        ["Claim", "Owner's answer", "Evidence"],
        dispute_rows(record, plan),
        "_No claim was impeached in this run._",
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[5], written=written))
    add("")
    add("---")
    add("")

    add("## 7. Declared footprint against actual")
    add("")
    add(
        "What each item said it would touch, against what its commit shows it touched. "
        "Planning R-10.3 defers concurrent execution until these agree across real plans, and "
        "this table is where the evidence accumulates."
    )
    add("")
    add(table(
        ["Item", "Declared but never touched", "Touched but never declared"],
        footprint_rows(record),
        "_No item recorded a footprint measurement._",
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[6], written=written))
    add("")
    add("---")
    add("")

    add("## 8. What this run says about the pipeline")
    add("")
    add(table(
        ["Finding", "Category", "State", "Summary"],
        finding_rows(record, plan),
        "_Nothing in this run's record meets any of the five recognition tests._",
    ))
    add("")
    add("The R-4.2 consistency checks, which decide how much of the above can be relied on:")
    add("")
    add(table(
        ["Check", "Result", "Detail"],
        [[entry.get("check"), "passed" if entry.get("ok") else "**failed**",
          entry.get("detail")] for entry in record.get("consistency") or []],
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[7], written=written))
    add("")
    add("---")
    add("")

    add("## 9. What may now be relied on")
    add("")
    add(_coverage_intro(record))
    add("")
    add(table(
        ["File", "Metric", "Before", "After", "Target", "Met"],
        coverage_rows(record),
        "_No coverage delta was declared by this plan._",
    ))
    add("")
    add(prose_slot(*PROSE_SLOTS[8], written=written))
    add("")
    return "\n".join(parts) + "\n"


def _suite_phrase(suite):
    if not suite.get("measured"):
        return "_not measured — " + (suite.get("note") or "no reason recorded") + "_"
    expected = suite.get("expected_failures") or []
    phrase = f"{suite.get('passed')} passing, {suite.get('failed')} failing"
    if expected:
        phrase += f" ({len(expected)} of them expected and named in section 5)"
    return phrase


def _coverage_intro(record):
    return (
        "Coverage is reported because the plan declared targets against it, and it is the "
        "weakest evidence in this document: it measures which lines ran, not whether anything "
        "would notice them changing. The mutation evidence in section 2 is the stronger "
        "measurement and it is the one the trust statement below is built on."
    )


def undelivered_rows(record, plan):
    rows = []
    order = ("failed", "stale", "skipped", "blocked-by-failure", "in-progress", "pending",
             "blocked-on-decision")
    for status in order:
        for entry in record.get("items") or []:
            if entry.get("status") != status:
                continue
            for item_id in sorted(entry.get("ids") or [], key=_key):
                block = plan.items.get(item_id)
                reason = ""
                if block is not None:
                    reason = (block.node.get("diagnosis") or "").strip()
                    if not reason and block.node.get("blocked-by"):
                        reason = (
                            "blocked on "
                            + ", ".join(block.node["blocked-by"])
                            + ", which the review sitting left unanswered"
                        )
                title = block.node.get("title") if block is not None else ""
                rows.append([f"{item_id} — {title}", status, reason or "_no reason recorded_"])
    return rows


def defect_rows(record, plan):
    decisions = {
        entry.get("defect"): entry for entry in record.get("decisions") or []
    }
    closeouts = {
        block.node.get("defect"): block.node for block in plan.closeouts.values()
    }
    rows = []
    for defect_id in sorted(record.get("defects") or [], key=_key):
        block = plan.defects.get(defect_id)
        node = block.node if block else None
        decision = decisions.get(defect_id) or {}
        closeout = closeouts.get(defect_id) or {}
        state = closeout.get("red-test-state")
        rows.append([
            defect_id,
            node.get("claim") if node else "",
            decision.get("option") or "_undecided_",
            closeout.get("decided-by") or "",
            f"`{run_record.short(decision.get('commit'))}`" if decision.get("commit")
            else "_none; this answer applies nothing_",
            {
                "standing": "still red, and stays red",
                "rewritten": "rewritten to assert what the code does",
                "marked": "marked as a known failure, so the suite reports green",
            }.get(state, "_not recorded_"),
        ])
    return rows


def dispute_rows(record, plan):
    answers = {
        entry.get("claim"): entry.get("option")
        for entry in record.get("dispute_decisions") or []
    }
    rows = []
    for claim_id in sorted(record.get("disputes") or [], key=_key):
        block = plan.claims.get(claim_id)
        evidence = (block.node.get("evidence") if block else None) or "_none recorded_"
        rows.append([
            claim_id,
            answers.get(claim_id) or "_left open; it stays on the ledger_",
            f"`{evidence}`" if not evidence.startswith("_") else evidence,
        ])
    return rows


def footprint_rows(record):
    rows = []
    for entry in record.get("footprint") or []:
        declared = entry.get("declared_only") or []
        actual = entry.get("actual_only") or []
        rows.append([
            entry.get("item"),
            ", ".join(f"`{path}`" for path in declared) if declared else "—",
            ", ".join(f"`{path}`" for path in actual) if actual else "—",
        ])
    return rows


def finding_rows(record, plan):
    rows = []
    for entry in record.get("findings") or []:
        block = plan.findings.get(entry.get("id"))
        summary = block.node.get("summary") if block else ""
        rows.append([entry.get("id"), entry.get("category"), entry.get("state"), summary])
    return rows


def coverage_rows(record):
    rows = []
    for row in record.get("coverage") or []:
        after = row.get("after")
        rows.append([
            f"`{row.get('file')}`",
            row.get("metric"),
            f"{row.get('before')}%",
            f"{after}%" if after is not None else "_never measured_",
            f"{row.get('target')}%",
            "yes" if row.get("met") else "no",
        ])
    return rows


def carried_forward(ledger_data, record):
    """Open ledger items this run did not raise, which the next assessment must reconcile."""
    if not ledger_data:
        return []
    raised = set(record.get("defects") or []) | set(record.get("disputes") or [])
    raised |= {entry.get("id") for entry in record.get("findings") or []}
    raised |= {entry.get("id") for entry in record.get("amendment_flags") or []}
    # And every work item this run handled. The ledger's `scope` entries are keyed by item id,
    # which appears in none of the four lists above, so without this every item the run failed
    # to deliver was reported as inherited from an earlier run — on a first close-out, from no
    # run at all. Same shape as the assembler once reading its own ledger entry as its own
    # baseline: closing a run writes this run's leavings into the ledger, after which the
    # ledger's open set includes them.
    for group in record.get("items") or []:
        raised |= set(group.get("ids") or [])
    rows = []
    for item in ledger_module.open_items(ledger_data):
        if item.get("id") in raised:
            continue
        rows.append([
            item.get("id"), item.get("kind"), item.get("since"), item.get("summary"),
        ])
    return rows


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--record", help="a run-record JSON file; defaults to the plan's block")
    parser.add_argument("--out", default=run_record.DEFAULT_REPORT)
    parser.add_argument("--ledger", default=run_record.DEFAULT_LEDGER)
    parser.add_argument("--assessment")
    parser.add_argument("--phase", default="executed", choices=("executed", "closed"))
    args = parser.parse_args()

    planio = siblings.planio()
    plan = planio.Plan(args.plan, assessment=args.assessment, phase=args.phase,
                       lint_writes=False)

    if args.record:
        with open(args.record, encoding="utf-8") as handle:
            record = json.load(handle)
    elif plan.record_block is not None:
        record = planlib.to_plain(plan.record_block.node)
    else:
        print(
            "no run record: run run_record.py --write first. R-5.1 makes the record the single "
            "source for every figure in the report, so there is nothing to assemble from.",
            file=sys.stderr,
        )
        return 2

    ledger_path = (
        args.ledger if os.path.isabs(args.ledger) else os.path.join(args.repo, args.ledger)
    )
    try:
        ledger_data = ledger_module.load(ledger_path)
    except ledger_module.LedgerError as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 2

    repository = (
        (plan.meta.node.get("repository") if plan.meta else None)
        or os.path.basename(os.path.abspath(args.repo))
    )
    target = args.out if os.path.isabs(args.out) else os.path.join(args.repo, args.out)
    written = existing_prose(target)
    text = build(record, plan, ledger_data, repository, args.plan, written)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)

    remaining = len(PROSE_SLOTS) - len(written)
    print(f"wrote {args.out} — {len(PROSE_SLOTS)} prose slot(s), {len(written)} carried over "
          f"from the previous assembly, {remaining} to fill")
    print("  Fill each slot between its PROSE markers, then run:")
    print(f"    python3 trace_report.py {args.out} --repo {args.repo}")
    print("  Every number you write must already appear in a table above it. That is not a "
          "style rule: R-5.1 fails the assembly on a number that does not trace to the record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

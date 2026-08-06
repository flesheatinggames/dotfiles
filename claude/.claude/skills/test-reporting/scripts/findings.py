#!/usr/bin/env python3
"""Derive the run's pipeline findings under R-8.1's fixed taxonomy, and number them (R-8.2).

A pipeline finding is evidence a run produces about the pipeline itself rather than about the
repository: the plan asked for something impossible, the assessment had gone stale, the
planner's reading of the code was wrong, the declared footprints did not match the real ones, a
script or a schema fell short in use. Five categories, closed, each with a recognition test in
``references/pipeline-findings.md``.

**Every finding is derived from the run record, never from an impression of how the run felt.**
R-9.2 forbids attributing an evidence class a run did not earn, and the same discipline applies
one level up: "the plan felt underspecified" is not a finding, and "WI-05 and WI-06 failed, and
their diagnoses both name information the plan did not carry" is.

**Identifiers are reconciled against the ledger before they are issued.** Two runs derive their
findings independently, so recognising the same problem twice needs a key both derivations
produce — the category plus the identifiers the finding is about. Matching on the summary text
would make a reworded sentence look like a new problem, which is precisely the failure R-8.2's
recurrence flag exists to catch: a finding that recurs across runs without being retired or
contested is worth more attention than a new one, and it can only be seen to recur if it keeps
its number.

Usage:
    python3 findings.py docs/test-plan.md --repo .
    python3 findings.py docs/test-plan.md --repo . --write     # pipeline-finding blocks
    python3 findings.py docs/test-plan.md --repo . --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger as ledger_module  # noqa: E402
import run_record  # noqa: E402
import siblings  # noqa: E402

planlib = siblings.planlib()

FINDING_INTRO = """\
What this run says about the pipeline rather than about the repository (R-8.1). Derived from
the run record by `findings.py` under a closed five-category taxonomy, numbered against the run
ledger so a recurring problem keeps the identifier it was first raised under. A finding is
retired only explicitly, with the change that addressed it named (R-7.5)."""

# The consistency checks whose failure is a defect in the pipeline's own machinery rather than
# a consequence of what the run did. `coverage-measured` is deliberately not here: an
# unmeasured coverage delta usually means the item never ran, which is a planning gap wearing a
# measurement's clothes, and it is sorted below by whether the item completed.
_TOOLING_CHECKS = {
    "run-summary-present",
    "run-summary-source",
    "statuses-agree",
    "registry-tests-committed",
    "commits-name-items",
    "footprint-measured",
}


def _key(identifier):
    tail = (identifier or "").rstrip("0123456789")
    number = (identifier or "")[len(tail):]
    return (tail, int(number) if number else 0)


def _ids(record, *statuses):
    out = []
    for entry in record.get("items") or []:
        if entry.get("status") in statuses:
            out.extend(entry.get("ids") or [])
    return sorted(set(out), key=_key)


def _signature(category, subjects):
    return f"{category}:{','.join(subjects)}" if subjects else category


# --------------------------------------------------------------------------------------
# The five derivations
# --------------------------------------------------------------------------------------


def planning_gaps(record, plan):
    """Items that failed or were never attempted for information the plan did not carry.

    Two shapes, kept apart because they cost different things. A `failed` item was attempted
    and the plan turned out to ask for something that did not work, which is the more
    interesting of the two. A `skipped` item was blocked on a decision the review sitting left
    unanswered — the plan was right to ask, and the gap is that the question reached execution
    still open.
    """
    out = []

    failed = _ids(record, "failed")
    blocked = _ids(record, "blocked-by-failure")
    if failed:
        diagnoses = []
        for item_id in failed:
            block = plan.items.get(item_id)
            text = (block.node.get("diagnosis") or "").strip() if block else ""
            diagnoses.append(f"{item_id}: {text[:240] or 'no diagnosis recorded'}")
        evidence = " | ".join(diagnoses)
        if blocked:
            evidence += (
                f" | {len(blocked)} further item(s) never ran behind them: "
                + ", ".join(blocked)
            )
        out.append({
            "category": "planning-gap",
            "subjects": failed,
            "summary": (
                f"{len(failed)} work item(s) were attempted and did not complete: "
                + ", ".join(failed)
            ),
            "evidence": evidence,
        })

    skipped = _ids(record, "skipped")
    if skipped:
        blockers = sorted({
            blocker
            for item_id in skipped
            for blocker in ((plan.items[item_id].node.get("blocked-by") or [])
                            if item_id in plan.items else [])
            if isinstance(blocker, str)
        })
        out.append({
            "category": "planning-gap",
            "subjects": skipped,
            "summary": (
                f"{len(skipped)} work item(s) reached execution still blocked on an unanswered "
                "question: " + ", ".join(skipped)
            ),
            "evidence": (
                "blocked by " + (", ".join(blockers) if blockers else "an unrecorded blocker")
                + ". The plan was right to escalate; the gap is that the question survived the "
                "review sitting unanswered and cost the run this work. Answering it makes the "
                "same items executable with no re-planning."
            ),
        })

    unmeasured_completed = _unmeasured_coverage(record, plan, completed=False)
    if unmeasured_completed:
        out.append({
            "category": "planning-gap",
            "subjects": sorted({row["file"] for row in unmeasured_completed}),
            "summary": (
                f"{len(unmeasured_completed)} declared coverage delta(s) were never measured "
                "because the item declaring them did not run"
            ),
            "evidence": "; ".join(
                f"{row['file']} {row['metric']} (target {row['target']}%)"
                for row in unmeasured_completed
            ) + ". A delta with no measurement is not a target that was missed.",
        })
    return out


def assessment_staleness(record, plan):
    """Items whose target moved between the assessment and this run, and what that cost."""
    stale = _ids(record, "stale")
    if not stale:
        return []
    claims = sorted({
        claim
        for item_id in stale
        for claim in ((plan.items[item_id].node.get("claims") or [])
                      if item_id in plan.items else [])
        if isinstance(claim, str)
    }, key=_key)
    diagnoses = []
    for item_id in stale:
        block = plan.items.get(item_id)
        text = (block.node.get("diagnosis") or "").strip() if block else ""
        diagnoses.append(f"{item_id}: {text[:240] or 'no diagnosis recorded'}")
    return [{
        "category": "assessment-staleness",
        "subjects": stale,
        "summary": (
            f"{len(stale)} work item(s) targeted code that had moved since the assessment: "
            + ", ".join(stale)
        ),
        "evidence": " | ".join(diagnoses) + (
            f" | the claim(s) {', '.join(claims)} are asserted by nothing as a result"
            if claims else ""
        ),
    }]


def claim_accuracy(record, plan):
    """Disputes, verifier rejections, and mutation checks that failed against a claim.

    All three are the same measurement from different angles: how often the planner's reading
    of the code was wrong. It is the figure that decides whether pinned claims are worth
    deriving at the scale stage two derives them at, and until something counted it there was
    no way to know.
    """
    out = []

    disputes = list(record.get("disputes") or [])
    if disputes:
        evidence = []
        for claim_id in disputes:
            block = plan.claims.get(claim_id)
            pointer = (block.node.get("evidence") if block else None) or "no evidence recorded"
            evidence.append(f"{claim_id}: {pointer}")
        out.append({
            "category": "planner-claim-accuracy",
            "subjects": sorted(disputes, key=_key),
            "summary": (
                f"{len(disputes)} pinned claim(s) were impeached by a faithful test: "
                + ", ".join(disputes)
            ),
            "evidence": " | ".join(evidence) + (
                ". A dispute is a planner error rather than a code defect: the claim's only "
                "backing was the planner's reading, and the reading did not hold."
            ),
        })

    rejections = []
    for block in plan.by_kind.get("execution-log", []):
        for entry in block.node.get("verifier") or []:
            if isinstance(entry, dict) and entry.get("verdict") in ("unfaithful", "weak"):
                rejections.append(
                    f"{block.node.get('item')} attempt {block.node.get('attempt')}: "
                    f"{entry.get('brief')} verdict {entry.get('verdict')}"
                )
    if rejections:
        out.append({
            "category": "planner-claim-accuracy",
            "subjects": sorted({line.split(" ")[0].rstrip(":") for line in rejections}),
            "summary": (
                f"{len(rejections)} fresh-context verification(s) rejected a test as "
                "unfaithful to its claim or as too weak to discriminate it"
            ),
            "evidence": " | ".join(rejections[:12]),
        })

    failures = []
    for item_id, block in sorted(plan.items.items(), key=lambda kv: _key(kv[0])):
        actuals = block.node.get("actuals")
        if not isinstance(actuals, dict):
            continue
        for check in actuals.get("checks") or []:
            if (
                isinstance(check, dict)
                and check.get("kind") == "mutation"
                and check.get("outcome") == "failed"
            ):
                failures.append(
                    f"{item_id}/{check.get('claim')}: "
                    f"{(check.get('detail') or '')[:200]}"
                )
    if failures:
        out.append({
            "category": "planner-claim-accuracy",
            "subjects": sorted({line.split("/")[0] for line in failures}),
            "summary": (
                f"{len(failures)} mutation check(s) failed to falsify the claim they were "
                "written for"
            ),
            "evidence": " | ".join(failures[:12]) + (
                ". A mutation check that cannot falsify its own claim proves the suite would "
                "not notice the behavior changing, which is the property the check exists to "
                "establish."
            ),
        })
    return out


def footprint_accuracy(record, plan):
    """The declared-versus-actual diff, which planning R-10.3 gates concurrent execution on."""
    rows = record.get("footprint") or []
    inaccurate = [
        row for row in rows if row.get("declared_only") or row.get("actual_only")
    ]
    if not inaccurate:
        return []
    exceeded = [row for row in inaccurate if row.get("actual_only")]
    detail = "; ".join(
        f"{row['item']}: "
        + (f"touched {', '.join(row['actual_only'])} outside its footprint" if row.get("actual_only") else "")
        + ("; " if row.get("actual_only") and row.get("declared_only") else "")
        + (f"declared but never touched {', '.join(row['declared_only'])}" if row.get("declared_only") else "")
        for row in inaccurate[:10]
    )
    return [{
        "category": "footprint-accuracy",
        "subjects": sorted({row["item"] for row in inaccurate}, key=_key),
        "summary": (
            f"{len(inaccurate)} of {len(rows)} measured item(s) had a footprint that did not "
            "match what the plan declared"
        ),
        "evidence": detail + (
            f". {len(exceeded)} of them touched a file nothing declared, which R-2.2 makes an "
            "item failure rather than a footprint widening. Planning R-10.3 gates concurrent "
            "execution on these two agreeing across real plans, so every entry here is a "
            "reason not to enable it yet."
            if exceeded else
            ". Over-declaration costs nothing at execution time and it does cost the wave "
            "computation, which schedules on declared footprints and therefore serialises "
            "slices that never needed to be."
        ),
    }]


def tooling_defects(record, plan):
    """Consistency failures, checks the runner could not run, and figures nothing produced."""
    out = []

    for check in record.get("consistency") or []:
        if check.get("ok") or check.get("check") not in _TOOLING_CHECKS:
            continue
        out.append({
            "category": "tooling-defect",
            "subjects": [check["check"]],
            "summary": (
                f"the R-4.2 consistency check `{check['check']}` failed, so the run record and "
                "the plan writeback disagree about what happened"
            ),
            "evidence": check.get("detail") or "no detail recorded",
        })

    not_run = []
    for item_id, block in sorted(plan.items.items(), key=lambda kv: _key(kv[0])):
        actuals = block.node.get("actuals")
        if not isinstance(actuals, dict):
            continue
        for check in actuals.get("checks") or []:
            if isinstance(check, dict) and check.get("outcome") == "not-run":
                not_run.append(
                    f"{item_id}/{check.get('kind')}: {(check.get('detail') or '')[:200]}"
                )
    if not_run:
        out.append({
            "category": "tooling-defect",
            "subjects": sorted({line.split("/")[0] for line in not_run}, key=_key),
            "summary": (
                f"{len(not_run)} completion check(s) could not be run, so what they would have "
                "established is unknown rather than established"
            ),
            "evidence": " | ".join(not_run[:12]),
        })

    unmeasured_ran = _unmeasured_coverage(record, plan, completed=True)
    if unmeasured_ran:
        out.append({
            "category": "tooling-defect",
            "subjects": sorted({row["file"] for row in unmeasured_ran}),
            "summary": (
                f"{len(unmeasured_ran)} coverage delta(s) declared by an item that completed "
                "have no measured figure"
            ),
            "evidence": "; ".join(
                f"{row['file']} {row['metric']}" for row in unmeasured_ran
            ) + (
                ". The work ran and the measurement did not, which is a gap in the tooling "
                "rather than in the plan: either the coverage report did not name this file "
                "or the parser did not recognise the entry."
            ),
        })

    suite = record.get("final_suite") or {}
    if suite.get("measured") is False and suite.get("command"):
        out.append({
            "category": "tooling-defect",
            "subjects": ["final-suite"],
            "summary": "the suite could not be measured at close-out",
            "evidence": suite.get("note") or "no detail recorded",
        })
    return out


def _unmeasured_coverage(record, plan, completed):
    """Coverage deltas with no `after` figure, split by whether their item actually ran.

    The split is the whole point. Unmeasured because the item never ran is a consequence of the
    run being partial, and belongs to the planning-gap finding beside the item itself.
    Unmeasured after the item completed is a hole in the measuring, and belongs to the tooling.
    Reporting both as one figure would let the second hide behind the first.
    """
    owner = {}
    for item_id, block in plan.items.items():
        for delta in block.node.get("coverage-delta") or []:
            if isinstance(delta, dict):
                owner[(delta.get("file"), delta.get("metric"))] = item_id

    out = []
    for row in record.get("coverage") or []:
        if row.get("after") is not None:
            continue
        item_id = owner.get((row.get("file"), row.get("metric")))
        block = plan.items.get(item_id) if item_id else None
        ran = bool(block) and block.node.get("status") in ("done", "done-with-defect")
        if ran == completed:
            out.append({
                "file": row.get("file"),
                "metric": row.get("metric"),
                "target": row.get("target"),
                "item": item_id,
            })
    return out


DERIVATIONS = (
    planning_gaps,
    assessment_staleness,
    claim_accuracy,
    footprint_accuracy,
    tooling_defects,
)


def unaccounted_narrowings(record, derived):
    """Narrowings that no derived finding explains, for the model to classify.

    R-9.1 makes finding derivation model work directed by the skill, downstream of computed
    figures and never the source of one. The five derivations above are the mechanical part:
    they read statuses, disputes, check outcomes, and footprint diffs, and they are exact. They
    are also blind to the part of the run record that is prose.

    A run where every item completed produces no derived finding at all, and can still record
    five narrowings — one of which says that slice zero installed a tool writing a generated
    directory and that nothing added it to `.gitignore`, because `.gitignore` was in no item's
    declared footprint. That is a planning gap by any reading of the recognition test, and no
    script is going to see it in a sentence. So this returns what the derivations did not
    explain, and the skill asks the model to classify each one under the taxonomy or say why it
    is not a finding.

    The matching is deliberately crude — a narrowing is accounted for when a subject one of the
    derived findings names appears in its text — because the cost of the two errors is not
    symmetric. Offering a narrowing the model then judges is not a finding costs a sentence.
    Withholding one costs the finding.
    """
    subjects = {subject for entry in derived for subject in entry.get("subjects", [])}
    out = []
    for entry in record.get("narrowings") or []:
        if not isinstance(entry, dict):
            continue
        text = f"{entry.get('what', '')} {entry.get('cost', '')}"
        if any(subject and subject in text for subject in subjects):
            continue
        out.append(entry)
    return out


# --------------------------------------------------------------------------------------
# Numbering, against the ledger
# --------------------------------------------------------------------------------------


def derive(record, plan):
    raw = []
    for derivation in DERIVATIONS:
        raw.extend(derivation(record, plan))
    for entry in raw:
        entry["signature"] = _signature(entry["category"], entry["subjects"])
    return raw


def number(raw, ledger_data):
    """Assign identifiers, reusing the ledger's where the signature already appears.

    A finding the ledger has seen keeps its number and comes back as `recurring`; a finding new
    to this run gets the next unused number and comes back as `open`. The next number is taken
    from the highest the ledger has ever issued rather than from the count of what is open, so
    a retired finding's number is never handed to something else — a reader who finds PF-03 in
    an old report and PF-03 in a new one must be reading about the same thing.
    """
    held = {}
    highest = 0
    if ledger_data:
        for entry in ledger_data.get("findings", []):
            identifier = entry.get("id") or ""
            if entry.get("signature"):
                held[entry["signature"]] = entry
            tail = identifier.split("-")[-1]
            if tail.isdigit():
                highest = max(highest, int(tail))

    out = []
    for entry in raw:
        previous = held.get(entry["signature"])
        if previous is not None:
            out.append({
                **entry,
                "id": previous.get("id"),
                "state": "recurring",
                "first-seen": previous.get("first_seen"),
                "occurrences": int(previous.get("occurrences") or 1) + 1,
            })
            continue
        highest += 1
        out.append({
            **entry,
            "id": f"PF-{highest:02d}",
            "state": "open",
            "occurrences": 1,
        })
    out.sort(key=lambda entry: _key(entry["id"]))
    return out


def write_findings(plan, planio, planlib, entries):
    """Write every finding block, and keep the run record's finding list in step with them.

    One transaction, because the two are a mirrored pair the linter checks in both directions:
    a record listing a finding the plan does not hold fails, and a finding block the record does
    not list fails. Written separately, whichever went first would introduce the other's failure
    and be rolled back — the same shape as the claim relabelling in `closeout.py`, and the
    reason `planio` grew transactions at all.

    When there is no record block yet the pair does not exist, and the transaction costs
    nothing.
    """
    with plan.transaction(f"{len(entries)} pipeline finding(s)"):
        for entry in entries:
            plan.upsert_block(
                planio.FINDING_SECTION,
                "pipeline-finding",
                block_fields(entry),
                {"id": entry["id"]},
                intro=FINDING_INTRO,
            )
        if plan.record_block is not None:
            record = planlib.to_plain(plan.record_block.node)
            record["findings"] = [
                {
                    "id": entry["id"],
                    "category": entry["category"],
                    "state": entry["state"],
                    "signature": entry["signature"],
                }
                for entry in entries
            ]
            plan.upsert_block(planio.RECORD_SECTION, "run-record", record, {})


def block_fields(entry, run_id=None):
    """One finding as the plan block the linter validates."""
    fields = {
        "id": entry["id"],
        "category": entry["category"],
        "state": entry["state"],
        "summary": entry["summary"],
        "evidence": entry["evidence"],
        "signature": entry["signature"],
    }
    if entry.get("first-seen") or run_id:
        fields["first-seen"] = entry.get("first-seen") or run_id
    if entry.get("occurrences", 1) > 1:
        fields["occurrences"] = entry["occurrences"]
    return fields


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--record", help="a run-record JSON file; defaults to the plan's block")
    parser.add_argument("--ledger", default=run_record.DEFAULT_LEDGER)
    parser.add_argument("--assessment")
    parser.add_argument("--phase", default="executed", choices=("executed", "closed"))
    parser.add_argument("--write", action="store_true",
                        help="write the pipeline-finding blocks into the plan")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    planio = siblings.planio()
    plan = planio.Plan(
        args.plan, assessment=args.assessment, phase=args.phase, lint_writes=args.write
    )

    if args.record:
        with open(args.record, encoding="utf-8") as handle:
            record = json.load(handle)
    elif plan.record_block is not None:
        record = planlib.to_plain(plan.record_block.node)
    else:
        # No record block yet, which is the normal case: findings are written *before* the
        # record, because the linter recomputes the record's finding list against the blocks
        # and a record written first would disagree with every block added after it. Building
        # the record in memory here is what makes the sequence one pass rather than three.
        #
        # The suite is deliberately left unmeasured in this build. Nothing in the derivations
        # reads a suite figure, and the one check that reads its *state* requires a command,
        # which the unmeasured record does not carry — so an in-memory build cannot invent the
        # tooling defect that says the suite could not be measured.
        record = run_record.build(
            plan, args.repo, run_record.DEFAULT_LOG_DIR, args.ledger,
            "", dict(run_record.UNMEASURED_SUITE), run_record.DEFAULT_REPORT,
        )

    ledger_path = (
        args.ledger if os.path.isabs(args.ledger) else os.path.join(args.repo, args.ledger)
    )
    try:
        ledger_data = ledger_module.load(ledger_path)
    except ledger_module.LedgerError as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 2

    raw = derive(record, plan)
    entries = number(raw, ledger_data)
    unclassified = unaccounted_narrowings(record, raw)

    if args.write:
        try:
            write_findings(plan, planio, planlib, entries)
        except planio.WriteRejected as rejected:
            print(str(rejected), file=sys.stderr)
            return 1
        print(f"wrote {len(entries)} pipeline finding(s) into {args.plan}")
        print("  Next: run_record.py --write, which measures the suite and records the "
              "R-4.2 consistency checks against the plan as it now stands.")

    if args.json:
        print(json.dumps(
            {"derived": entries, "unclassified_narrowings": unclassified},
            indent=2, ensure_ascii=False,
        ))
        return 0

    if not entries:
        print("no derived pipeline findings: nothing in this run's statuses, disputes, check "
              "outcomes, or footprint diffs meets any of the five recognition tests")
    else:
        print(f"{len(entries)} derived pipeline finding(s):")
        for entry in entries:
            marker = "recurring" if entry["state"] == "recurring" else "new"
            print(f"  {entry['id']}  [{entry['category']}] ({marker}"
                  + (f", {entry['occurrences']} runs" if entry["occurrences"] > 1 else "") + ")")
            print(f"      {entry['summary']}")
        recurring = [entry for entry in entries if entry["state"] == "recurring"]
        if recurring:
            print(f"\n  {len(recurring)} finding(s) have recurred without being retired or "
                  "contested. R-8.2 flags these deliberately: a problem the pipeline keeps "
                  "producing is the raw material for a requirements amendment.")

    if unclassified:
        print(f"\n  {len(unclassified)} narrowing(s) that none of the derived findings "
              "explains. R-9.1 makes finding derivation model work, and this is the part of it "
              "no script can do — read each one and either write a `pipeline-finding` block "
              "for it under the taxonomy, or record why it is not one:\n")
        for entry in unclassified:
            print(f"    - {entry.get('what')}")
        print("\n  references/pipeline-findings.md gives a recognition test per category. The "
              "dividing line: if this repository were replaced with a different one, would the "
              "problem still be there? Number any block you add from PF-"
              f"{_next_number(entries, ledger_data):02d} upward.")
    return 0


def _next_number(entries, ledger_data):
    highest = 0
    for source in (entries or []), ((ledger_data or {}).get("findings") or []):
        for entry in source:
            tail = (entry.get("id") or "").split("-")[-1]
            if tail.isdigit():
                highest = max(highest, int(tail))
    return highest + 1


if __name__ == "__main__":
    sys.exit(main())

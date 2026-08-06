#!/usr/bin/env python3
"""Extract what each gate brief needs, and nothing else (R-6.3, R-6.6).

The orchestrator writes the brief; this script supplies the facts it is written from. The
division is R-10.1's: deterministic work is a bundled script and model work is narration.

**This exists because of R-7.2, and that is worth stating rather than implying.** The
orchestrator's context stays thin by rule — it consumes the state script's output and each
stage's exit summary, and does not read the full artifacts. An orchestrator that has read a
two-thousand-line plan is an orchestrator tempted to have opinions about it, and R-9.2 forbids
it from having any. So the escalations, the decisions, the ratification list's size, the target
proposal, and the close-out sheet's answered count are extracted here and handed over as a
bounded set of facts, rather than the orchestrator paging through the plan looking for them.

**Nothing here recommends anything.** Where a plan records its own recommendation on an
escalation, this script copies it and labels it as the plan's — R-9.2 permits a brief to
restate a stage's recorded recommendation and forbids it from adding the orchestrator's own,
and the label is what keeps the two distinguishable in the brief that gets written from this.

Usage:
    python3 gate_brief.py docs/test-plan.md --gate 1 --repo .
    python3 gate_brief.py docs/test-plan.md --gate 2 --repo . --sheet docs/test-closeout.md
"""

import argparse
import json
import os
import sys

import siblings

# R-10.3: a gate brief is honest about scale. These are the thresholds at which the brief
# stops describing the sitting as short, and they exist so that the honesty is a property of
# the extraction rather than of whoever is writing that day.
#
# Their basis is the two real plans and the sizing heuristic behind them. `design-os` came out
# at 16 claims and `sbcf-app` at 37, and the heuristic caps a plan at 8 slices of 8 to 25
# claims — so about 200 is the ceiling and the realistic worst case is around that. A list of
# 40 is therefore not an outlier to be mentioned in passing; it is a fifth of the maximum the
# planner can produce, and a brief that presents it as a quick read has misdescribed the ask.
SITTING_THRESHOLDS = (
    (0, "short", "a few minutes"),
    (15, "moderate", "half an hour or so"),
    (40, "long", "an hour or more, and worth scheduling rather than squeezing in"),
    (80, "very long", "a sitting of its own, and a candidate for raising the value line and "
                      "re-planning rather than pushing through"),
)


def sitting_estimate(count):
    """How long the ratification list will take, named rather than guessed at.

    Returns (scale, estimate). The estimate is deliberately a range in words rather than a
    number: a figure here would be a figure nobody computed, and R-8.1's discipline about
    never stating a number you did not measure applies to the orchestrator's own output as
    much as to a report's.
    """
    scale, estimate = SITTING_THRESHOLDS[0][1], SITTING_THRESHOLDS[0][2]
    for threshold, name, words in SITTING_THRESHOLDS:
        if count >= threshold:
            scale, estimate = name, words
    return scale, estimate


def answered_defects(defects, answers, problems):
    """Which defects carry a *complete* answer, judged by stage four's own validator.

    Membership in the answer set is not the test, and using it as one is a mistake that reads
    as correct until you see the output. `closeout.py --brief` writes an `answer` block per
    defect with every field left blank, so every defect is in the answer set from the moment
    the sheet is written — and a brief built on membership reports a wholly unanswered sheet as
    "1 of 1 answered" while also reporting it incomplete, which is two contradictory sentences
    about the same fact.

    So a defect counts as answered when it has a block *and* nothing in `validate_answers`'
    output names it. That keeps stage four's validator as the single authority on what a
    complete answer is, which is the same reason the sheet is read with `read_sheet` rather
    than parsed here.
    """
    named = set()
    for problem in problems:
        for defect_id in defects:
            if defect_id in problem:
                named.add(defect_id)
    return [d for d in defects if d in answers and d not in named]


def answered_disputes(disputes, dispute_answers):
    """Which disputes carry an answer. Optional, so the only test is that an option was chosen.

    `validate_answers` does not police disputes, because answering one is optional by design —
    a dispute is a planner error with evidence captured and nothing red on the branch, so
    leaving one open is a legitimate outcome. The blank template block still has to be told
    from a filled one, and the `option` field is what distinguishes them.
    """
    out = []
    for claim_id in disputes:
        entry = dispute_answers.get(claim_id)
        if entry and (entry[0].get("option") or "").strip():
            out.append(claim_id)
    return out


def load(plan_path):
    planlib = siblings.planlib()
    by_kind, problems, _ = planlib.load_plan(plan_path)
    return by_kind, problems


def _single(by_kind, kind):
    blocks = by_kind.get(kind) or []
    return blocks[0].node if blocks and blocks[0].node else None


def _nodes(by_kind, kind):
    return [block.node for block in (by_kind.get(kind) or []) if block.node]


def _plain(value):
    """Strip the parser's line-tracking wrappers so the result is JSON-serialisable."""
    planlib = siblings.planlib()
    return planlib.to_plain(value)


def gate_one(plan_path, repo, assessment_path, ledger_path):
    """R-6.3: everything the owner decides at the review sitting, with where each is recorded.

    The last part is the one that is easy to leave out and the one the requirement names
    explicitly: each decision comes with *where it lives in the artifacts and what recording it
    looks like*. A brief that says "resolve the escalations" and does not say that a resolution
    is a `resolution` field on the escalation block leaves the owner to find that out, and the
    whole point of this gate is that they can act without opening the specification.
    """
    by_kind, problems = load(plan_path)
    meta = _single(by_kind, "plan-meta") or {}
    target = _single(by_kind, "target") or {}
    claims = _nodes(by_kind, "claim")
    items = _nodes(by_kind, "work-item")
    slices = _nodes(by_kind, "slice")

    unratified = [claim for claim in claims if claim.get("label") == "pinned"]
    cited = [claim for claim in claims if claim.get("label") == "cited"]
    already = [claim for claim in claims if claim.get("label") == "ratified"]
    scale, estimate = sitting_estimate(len(unratified))

    blockers = []
    for kind in ("escalation", "decision"):
        for node in _nodes(by_kind, kind):
            blockers.append({
                "id": node.get("id"),
                "class": node.get("class") or kind,
                "title": node.get("title") or node.get("question"),
                "resolved": bool(node.get("resolution")),
                "blocks": _plain(node.get("blocks") or []),
                "options": [
                    {
                        "id": option.get("id"),
                        "summary": option.get("summary"),
                        "consequence": option.get("consequence"),
                        "rewrites_items": sorted({
                            effect.get("item") for effect in (option.get("effect") or [])
                            if effect.get("item")
                        }),
                    }
                    for option in _plain(node.get("options") or [])
                ],
                # Copied and labelled as the plan's, never merged into the orchestrator's own
                # voice. R-9.2 permits restating a stage's recommendation and forbids adding
                # one, and an unlabelled restatement is indistinguishable from an addition.
                "plan_recommendation": node.get("recommendation"),
                "recorded_as": (
                    f"the `resolution` field on the `yaml {node.get('class') or kind}` block "
                    f"with `id: {node.get('id')}`, naming the option and the decider"
                ),
            })

    flagged = [
        {"id": node.get("id"), "summary": node.get("summary") or node.get("title")}
        for node in _nodes(by_kind, "flagged")
    ]

    return {
        "gate": "G1",
        "repository": meta.get("repository"),
        "plan": plan_path,
        "assessment": assessment_path,
        "has_ledger": os.path.isfile(os.path.join(repo, ledger_path)),
        "parse_problems": len(problems),
        "counts": {
            "slices": len(slices),
            "work_items": len(items),
            "claims": len(claims),
            "claims_pinned": len(unratified),
            "claims_cited": len(cited),
            "claims_already_ratified": len(already),
            "blockers": len(blockers),
            "blockers_unresolved": sum(1 for b in blockers if not b["resolved"]),
        },
        "ratification": {
            "count": len(unratified),
            "scale": scale,
            "estimate": estimate,
            "recorded_as": (
                "on each `yaml claim` block: change `label: pinned` to `label: ratified` and "
                "add `ratified-by` and `ratified-on`"
            ),
            "note": (
                "Only pinned claims need ratifying. A cited claim already carries a "
                "document's authority and appears here for reading rather than for deciding."
            ),
        },
        "blockers": blockers,
        "flagged": flagged,
        "target": {
            "form": target.get("form"),
            "axes": [
                {"name": axis.get("name"), "from": axis.get("from"), "to": axis.get("to"),
                 "basis": axis.get("basis")}
                for axis in _plain(target.get("axes") or [])
            ],
            "rederivation_trigger": target.get("rederivation_trigger"),
            "approved": bool(target.get("approved")),
            "recorded_as": (
                "an `approved` field on the `yaml target` block. This is separate from plan "
                "approval on purpose: `target.approved` approves a coverage number and "
                "`plan-meta.approved` approves the plan. An owner may approve the plan while "
                "deferring the number, which is what `form: delta-with-rederivation` is for."
            ),
        },
        "approval": {
            "recorded": bool(meta.get("approved")),
            "recorded_as": (
                "an `approved` block on `yaml plan-meta`, carrying `by`, `date`, and a `note`"
            ),
        },
        "scope": _plain(meta.get("scope") or {}),
        "inherited_degradations": _plain(meta.get("inherited_degradations") or []),
    }


def gate_two(plan_path, repo, sheet_path):
    """R-6.6: the close-out sheet's shape, judged by stage four's own validator.

    What this does *not* do is read the defects out of the plan and compose its own account of
    them. The sheet stage four writes already carries each defect with its claim, its
    authority, what the code actually does, the red test, the fresh-context verification that
    let it stand, and the four options with what each costs. The orchestrator's brief points at
    that sheet and reports how much of it is answered; a second rendering of the same defects
    would be a second description of a decision the owner is about to make from the first.
    """
    closeout = siblings.closeout()
    planio = siblings.planio()

    plan = planio.Plan(plan_path, phase="closed", lint_writes=False)
    defects = sorted(plan.defects)
    disputes = sorted(
        claim_id for claim_id, block in plan.claims.items()
        if block.node.get("label") == "disputed"
    )

    exists = os.path.isfile(sheet_path)
    answers, dispute_answers, problems = {}, {}, []
    if exists:
        try:
            answers, dispute_answers = closeout.read_sheet(sheet_path)
        except closeout.CloseoutError as error:
            problems = [str(error)]
        else:
            problems = closeout.validate_answers(plan, answers, sheet_path)

    answered = answered_defects(defects, answers, problems)
    disputes_answered = answered_disputes(disputes, dispute_answers)

    return {
        "gate": "G2",
        "repository": (plan.meta.node.get("repository") if plan.meta else None) or repo,
        "plan": plan_path,
        "sheet": sheet_path,
        "sheet_exists": exists,
        "empty_gate": not defects,
        "counts": {
            "defects": len(defects),
            "answered": len(answered),
            "unanswered": len(defects) - len(answered),
            "disputes": len(disputes),
            "disputes_answered": len(disputes_answered),
        },
        "defects": defects,
        "defects_answered": answered,
        "defects_unanswered": [d for d in defects if d not in answered],
        "disputes": disputes,
        "options": list(closeout.OPTIONS),
        "option_text": dict(closeout.OPTION_TEXT),
        "restricted_option": {
            "option": "downgrade",
            "why": (
                "It is the only answer that makes a real failure stop being visible, and the "
                "only one no agent may reach. The sheet's own validator rejects a decider "
                "name that looks automated."
            ),
        },
        "validation_problems": problems,
        "complete": exists and not problems,
        "recorded_as": (
            "the `yaml answer` block under each defect in the sheet, then "
            "`closeout.py --apply`. The gate is one sitting: a partially answered sheet is "
            "refused rather than half-applied."
        ),
        "note_on_scale": (
            "The gate is empty — this run registered no defects. It still gets applied: the "
            "run closes by running `--apply` over the empty sheet, which is what writes the "
            "records the closed phase requires."
            if not defects else
            f"{len(defects)} defect(s) to answer, each ending in a consequence applied to the "
            "branch. One of the four options is available to nobody but the owner."
        ),
    }


def render_one(payload):
    """A readable rendering, for a person running this at a terminal rather than a caller."""
    lines = [f"gate: {payload['gate']}", f"repository: {payload.get('repository')}", ""]
    for key, value in payload["counts"].items():
        lines.append(f"  {key.replace('_', ' ')}: {value}")
    lines.append("")
    if payload["gate"] == "G1":
        ratification = payload["ratification"]
        lines.append(
            f"ratification list: {ratification['count']} pinned claim(s) — a "
            f"{ratification['scale']} sitting, {ratification['estimate']}"
        )
        lines.append(f"  recorded as: {ratification['recorded_as']}")
        lines.append("")
        for blocker in payload["blockers"]:
            state = "resolved" if blocker["resolved"] else "OPEN"
            lines.append(f"{blocker['id']} [{blocker['class']}] {state}: {blocker['title']}")
            for option in blocker["options"]:
                rewrites = (
                    f" (rewrites {', '.join(option['rewrites_items'])})"
                    if option["rewrites_items"] else ""
                )
                lines.append(f"    {option['id']}: {option['summary']}{rewrites}")
            lines.append(f"    recorded as: {blocker['recorded_as']}")
            lines.append("")
        lines.append(f"plan approval recorded: {payload['approval']['recorded']}")
        lines.append(f"  recorded as: {payload['approval']['recorded_as']}")
        lines.append(f"target approved: {payload['target']['approved']}")
    else:
        lines.append(payload["note_on_scale"])
        lines.append("")
        if payload["defects_unanswered"]:
            lines.append("unanswered: " + ", ".join(payload["defects_unanswered"]))
        for problem in payload["validation_problems"]:
            lines.append(f"  {problem}")
        lines.append("")
        lines.append(f"complete: {payload['complete']}")
        lines.append(f"recorded as: {payload['recorded_as']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Extract what a gate brief needs, and nothing else (R-6.3, R-6.6)."
    )
    parser.add_argument("plan")
    parser.add_argument("--gate", choices=("1", "2"), required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--assessment", default="docs/test-assessment.md")
    parser.add_argument("--ledger", default="docs/test-ledger.json")
    parser.add_argument("--sheet", default="docs/test-closeout.md")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    if not os.path.isfile(arguments.plan):
        print(f"no plan at {arguments.plan}", file=sys.stderr)
        return 2

    if arguments.gate == "1":
        payload = gate_one(arguments.plan, arguments.repo, arguments.assessment,
                           arguments.ledger)
    else:
        payload = gate_two(arguments.plan, arguments.repo, arguments.sheet)

    if arguments.json:
        print(json.dumps(payload, indent=2))
    else:
        sys.stdout.write(render_one(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""R-7.2's check: every open ledger item is confirmed, updated, or contested — never dropped.

This is the mechanism that makes the run ledger binding rather than descriptive, and it is the
only mechanism under which an open defect provably cannot vanish between runs. The shape is
lifted directly from the planning linter's discharge discipline for open questions, which
exists because a question that is merely written down is a question that gets forgotten: a
later document that simply does not mention it reads exactly like a document that resolved it.

**It lives in the reporting skill and is imported by the assessment skill**, which is the only
place in this suite where a later stage's code runs inside an earlier one. The alternative was
a second implementation of the same comparison in `check_index.py`, and a second implementation
of a rule is a second opinion about what the rule says. The dependency is one-directional and
optional: `check_index.py --ledger` is the only thing that reaches for it, and when the
reporting skill is not installed that flag reports so rather than failing obscurely.

**This module deliberately imports nothing from the other skills.** It reads JSON out of fenced
Markdown blocks with about thirty lines of its own code. That is duplication of a sort, and it
buys the property that matters here: the assessment stage can import this file by path without
inheriting the whole four-skill install assumption.

Usage:
    python3 reconcile.py docs/test-ledger.json docs/test-assessment.md
    python3 reconcile.py docs/test-ledger.json docs/test-assessment.md --json
"""

import argparse
import json
import os
import re
import sys

# The three dispositions R-7.2 permits. There is no fourth, and in particular there is no
# "still investigating": an item nobody has looked at is `confirmed` with that as its evidence,
# which is a statement somebody has to write down and can be held to.
DISPOSITIONS = ("confirmed", "updated", "contested")

# The index version that first carries a `reconciliation` array. An older index is not
# malformed — it predates the section — so it is routed to a narrow backfill rather than
# refused, exactly as a 1.0 index is routed today for its missing testability section.
RECONCILIATION_VERSION = "1.2"

_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")


class ReconcileError(Exception):
    """The check could not be run, as distinct from the check failing."""


def extract_json_block(text, info):
    """The body of the first fenced block whose info string matches, or None."""
    lines = text.split("\n")
    fence = None
    body = []
    for line in lines:
        match = _FENCE_RE.match(line)
        if fence is None:
            if match and match.group(3).strip() == info:
                fence = match.group(2)
                body = []
            continue
        if match and match.group(2)[0] == fence[0] and len(match.group(2)) >= len(fence):
            return "\n".join(body)
        body.append(line)
    return None


def read_index(path):
    """The assessment's machine-readable index, or a stop saying which backfill is needed."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise ReconcileError(f"cannot read {path}: {error}") from error

    body = extract_json_block(text, "json assessment-index")
    if body is None:
        raise ReconcileError(
            f"{path} has no machine-readable index, so there is nothing to reconcile against. "
            "Run the test-assessment skill in backfill mode against this report first."
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise ReconcileError(
            f"the assessment index in {path} is not valid JSON: {error.msg} at line "
            f"{error.lineno}"
        ) from error


def _version_tuple(value):
    try:
        return tuple(int(part) for part in str(value).split("."))
    except ValueError:
        return (0,)


def reconciliation_of(index, path):
    """The index's `reconciliation` array, with the version routing R-7.2 needs.

    A 1.1 index has no such array and is not wrong for lacking one; it was written before the
    ledger existed. What it needs is a bounded backfill — read the ledger, write a disposition
    per open item — rather than a re-assessment, and saying which of those two is needed is the
    whole point of routing rather than refusing.
    """
    version = index.get("schema_version") or index.get("index_version")
    if _version_tuple(version) < _version_tuple(RECONCILIATION_VERSION):
        raise ReconcileError(
            f"{path} carries index schema version {version!r} and reconciliation arrived in "
            f"{RECONCILIATION_VERSION}. This is a backfill, not a re-assessment: read the "
            "ledger's open items, write one reconciliation entry per item with its "
            "disposition and evidence, and set the index version. Nothing is re-measured."
        )
    entries = index.get("reconciliation")
    if entries is None:
        raise ReconcileError(
            f"{path} is at index schema version {version!r} and carries no `reconciliation` "
            "array. At this version the array is required, and an empty one is how a report "
            "says the ledger held nothing open."
        )
    if not isinstance(entries, list):
        raise ReconcileError(f"{path}'s `reconciliation` is not an array")
    return entries


def check(open_items, entries, assessment_path):
    """Compare what is open against what the assessment disposed of.

    Returns a list of problems. Each names the item, so the remedy is always a specific
    sentence somebody has to write rather than a general instruction to be more thorough.
    """
    problems = []
    by_id = {}
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append({
                "rule": "reconciliation-malformed",
                "item": None,
                "message": "a reconciliation entry is not an object",
            })
            continue
        identifier = entry.get("item") or entry.get("id")
        if not identifier:
            problems.append({
                "rule": "reconciliation-malformed",
                "item": None,
                "message": "a reconciliation entry names no item",
            })
            continue
        if identifier in by_id:
            problems.append({
                "rule": "reconciliation-duplicate",
                "item": identifier,
                "message": f"{identifier} is reconciled twice, so the report says two things "
                           "about one item",
            })
            continue
        by_id[identifier] = entry

    for item in open_items:
        identifier = item.get("id")
        entry = by_id.pop(identifier, None)
        if entry is None:
            problems.append({
                "rule": "open-item-dropped",
                "item": identifier,
                "message": (
                    f"{identifier} is open in the ledger ({item.get('kind')}, since "
                    f"{item.get('since')}) and {os.path.basename(assessment_path)} does not "
                    "mention it"
                ),
                "fix": (
                    "R-7.2: every open ledger item is explicitly confirmed (still true), "
                    "updated (changed, with evidence), or contested (disputed, with "
                    "evidence). Silence is none of the three, and silence is exactly what a "
                    "resolved item looks like — which is why this is a failure rather than a "
                    "warning. Add a reconciliation entry for "
                    f"{identifier}: {item.get('summary') or ''}"
                ),
            })
            continue
        disposition = entry.get("disposition")
        if disposition not in DISPOSITIONS:
            problems.append({
                "rule": "reconciliation-bad-disposition",
                "item": identifier,
                "message": f"{identifier} is reconciled with disposition "
                           f"{disposition!r}, which is not one of {list(DISPOSITIONS)}",
            })
        if not (entry.get("evidence") or "").strip():
            problems.append({
                "rule": "reconciliation-without-evidence",
                "item": identifier,
                "message": f"{identifier} is reconciled {disposition!r} with no evidence",
                "fix": (
                    "All three dispositions carry evidence. `confirmed` needs it most, not "
                    "least: it is the disposition that costs nothing to write and asserts the "
                    "most — that somebody looked and the item is still true."
                ),
            })

    for identifier, entry in sorted(by_id.items()):
        problems.append({
            "rule": "reconciliation-unknown-item",
            "item": identifier,
            "message": (
                f"the assessment reconciles {identifier}, which the ledger does not hold open"
            ),
            "fix": (
                "Either the item was disposed of in the ledger and the entry is stale, or the "
                "identifier is misspelled. A reconciliation entry for something that is not "
                "open reads as diligence and discharges nothing."
            ),
        })
    return problems


def run(ledger_path, assessment_path):
    """The whole check. Returns (problems, open_item_count)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ledger as ledger_module  # noqa: PLC0415

    try:
        data = ledger_module.load(ledger_path)
    except ledger_module.LedgerError as error:
        raise ReconcileError(str(error)) from error
    if data is None:
        raise ReconcileError(
            f"no ledger at {ledger_path}. Reconciliation binds a repository that has a "
            "ledger; a repository with none is on its first run and has nothing to reconcile."
        )
    items = ledger_module.open_items(data)
    index = read_index(assessment_path)
    entries = reconciliation_of(index, assessment_path)
    return check(items, entries, assessment_path), len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ledger")
    parser.add_argument("assessment")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        problems, open_count = run(args.ledger, args.assessment)
    except ReconcileError as error:
        if args.json:
            print(json.dumps({"ok": False, "stop": str(error)}, indent=2))
        else:
            print(f"STOP: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(
            {"ok": not problems, "open_items": open_count, "problems": problems},
            indent=2, ensure_ascii=False,
        ))
        return 1 if problems else 0

    if not problems:
        print(f"ok: {args.assessment} reconciles all {open_count} open ledger item(s)")
        return 0

    print(f"FAILED: {args.assessment} — {len(problems)} problem(s) against "
          f"{args.ledger} ({open_count} open item(s))\n")
    for problem in problems:
        print(f"  [{problem['rule']}] {problem['message']}")
        if problem.get("fix"):
            print(f"    fix: {problem['fix']}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())

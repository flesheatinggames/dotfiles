#!/usr/bin/env python3
"""The run ledger: read it, append to it, and ask it what is still open (R-7.1).

**A note on the word, because this project already uses it twice.** The imaginary repository
the linter fixtures describe is called `ledger`, and `partition.py` in the planning skill emits
a file-and-symbol accountability list it calls a ledger. Neither is this. This one is always
*the run ledger* in prose and `docs/test-ledger.json` on disk, and the planning skill's is
always *the derivation ledger*. Nothing is renamed; the qualification is just never dropped.

**One file rather than a directory of per-run entries.** Reconciliation's central query is
"what is open right now", which a single file answers by reading it and a directory answers
only by folding every entry in order — and a fold whose order is wrong produces a plausible
answer rather than an error. The single file also gives a readable git diff per run, which is
what makes the ledger auditable by a person rather than only by a script. The cost is merge
conflicts if two runs ever proceed in parallel, and the pipeline is serial by construction: one
work branch, merged by the owner before the next run starts.

**Append-only, through this script.** Not because hand-editing is impossible — it is a JSON
file — but because every append here is a merge against what is already open, and doing that
merge by hand is how an open defect gets replaced rather than carried. R-7.1 says appended by
bundled scripts only, and this is the script.

**Closing an item is always explicit.** R-8.2 says a pipeline finding is retired only
explicitly, and the same discipline is applied to defects, disputes, and amendment flags for a
reason the retirement rule does not state: the alternative is inference, and inference here
means concluding that a defect is fixed because its test did not fail in a run that may not
have run it. `--append` reports closure *candidates* and closes nothing.

Usage:
    python3 ledger.py docs/test-ledger.json --open
    python3 ledger.py docs/test-ledger.json --init --repository my-app
    python3 ledger.py docs/test-ledger.json --append run-record.json
    python3 ledger.py docs/test-ledger.json --close-defect DF-1 --commit a1b2c3d \\
            --evidence "test_parse_amount_reads_the_german_separator passes at a1b2c3d"
    python3 ledger.py docs/test-ledger.json --retire-finding PF-01 \\
            --by "slice sizing heuristic amended, planning changelog 2026-08-09"
    python3 ledger.py docs/test-ledger.json --validate
"""

import argparse
import json
import os
import re
import sys

LEDGER_VERSION = "1.0"

# The five kinds of thing that can be open, in the order a reader should meet them: a defect
# blocks, a dispute misinforms the next plan, a document that is wrong misinforms everyone, a
# pipeline finding is about the tooling, and undelivered scope is work nobody did.
OPEN_KINDS = ("defect", "dispute", "amendment-flag", "pipeline-finding", "scope")

DEFECT_STATES = {"open", "fixed", "downgraded", "requirement-amended", "contested"}
DISPUTE_STATES = {"open", "corrected", "contested"}
FLAG_STATES = {"open", "amended", "contested"}
FINDING_STATES = {"open", "recurring", "retired", "contested"}
SCOPE_STATES = {"open", "delivered", "abandoned"}

# The states that mean "a later run still owes this an answer". Everything else has been
# disposed of, with the disposal recorded beside it.
OPEN_STATES = {
    "defect": {"open"},
    "dispute": {"open"},
    "amendment-flag": {"open"},
    "pipeline-finding": {"open", "recurring"},
    "scope": {"open"},
}

_ARRAYS = (
    "runs", "claims", "defects", "disputes", "amendment_flags", "findings", "scope",
    "decisions", "footprint_accuracy",
)


class LedgerError(Exception):
    """Something is wrong with the ledger itself, rather than with what is in it."""


# --------------------------------------------------------------------------------------
# Reading and writing
# --------------------------------------------------------------------------------------


def empty(repository):
    return {
        "ledger_version": LEDGER_VERSION,
        "repository": repository,
        "runs": [],
        "claims": [],
        "defects": [],
        "disputes": [],
        "amendment_flags": [],
        "findings": [],
        "scope": [],
        "decisions": [],
        "footprint_accuracy": [],
    }


def load(path):
    """Read the ledger, or return None when there is none.

    A missing ledger is not an error: the first run of the pipeline against a repository has
    none, and the reconciliation obligation only exists once one does.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        raise LedgerError(
            f"{path} is not valid JSON: {error.msg} at line {error.lineno}. The ledger is the "
            "one artifact that binds later runs, so a damaged one is a stop rather than "
            "something to work around. Recover it from git history."
        ) from error
    if not isinstance(data, dict):
        raise LedgerError(f"{path} does not hold a JSON object")
    version = data.get("ledger_version")
    if version != LEDGER_VERSION:
        raise LedgerError(
            f"{path} is at ledger_version {version!r} and this script writes "
            f"{LEDGER_VERSION!r}. Versions are handled the way the assessment index handles "
            "them: an older ledger is routed to a narrow migration rather than refused, and "
            "there is no migration to write yet because there has been no earlier version."
        )
    for name in _ARRAYS:
        data.setdefault(name, [])
    return data


def save(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


# --------------------------------------------------------------------------------------
# The open-items query
# --------------------------------------------------------------------------------------


def open_items(data):
    """Everything a later run owes an answer for, as a flat list in a fixed order.

    This is the query the whole single-file decision was made for, and it is deliberately the
    simplest function in the module: read the arrays, filter by state, sort. Reconciliation,
    the planner's consistency rules, and the report's carried-forward section all consume this
    one list, so any cleverness here would be cleverness three consumers inherit.
    """
    out = []
    for entry in data.get("defects", []):
        if entry.get("state") in OPEN_STATES["defect"]:
            out.append({
                "kind": "defect",
                "id": entry.get("id"),
                "summary": entry.get("summary") or f"defect against {entry.get('claim')}",
                "since": entry.get("raised_in"),
                "detail": {
                    "claim": entry.get("claim"),
                    "test": entry.get("test"),
                    "decision": entry.get("decision"),
                },
            })
    for entry in data.get("disputes", []):
        if entry.get("state") in OPEN_STATES["dispute"]:
            out.append({
                "kind": "dispute",
                "id": entry.get("claim"),
                "summary": entry.get("summary") or f"{entry.get('claim')} is disputed",
                "since": entry.get("raised_in"),
                "detail": {"evidence": entry.get("evidence")},
            })
    for entry in data.get("amendment_flags", []):
        if entry.get("state") in OPEN_STATES["amendment-flag"]:
            out.append({
                "kind": "amendment-flag",
                "id": entry.get("id"),
                "summary": entry.get("passage") or entry.get("document"),
                "since": entry.get("raised_in"),
                "detail": {"document": entry.get("document")},
            })
    for entry in data.get("findings", []):
        if entry.get("state") in OPEN_STATES["pipeline-finding"]:
            out.append({
                "kind": "pipeline-finding",
                "id": entry.get("id"),
                "summary": entry.get("summary"),
                "since": entry.get("first_seen"),
                "detail": {
                    "category": entry.get("category"),
                    "state": entry.get("state"),
                    "occurrences": entry.get("occurrences"),
                },
            })
    for entry in data.get("scope", []):
        if entry.get("state") in OPEN_STATES["scope"]:
            out.append({
                "kind": "scope",
                "id": entry.get("id"),
                "summary": entry.get("summary"),
                "since": entry.get("raised_in"),
                "detail": {"status": entry.get("status"), "reason": entry.get("reason")},
            })
    out.sort(key=lambda entry: (OPEN_KINDS.index(entry["kind"]), _id_key(entry["id"])))
    return out


def _id_key(identifier):
    """Sort identifiers by their numeric tail, so DF-2 precedes DF-10."""
    text = identifier or ""
    head = text.rstrip("0123456789")
    tail = text[len(head):]
    return (head, int(tail) if tail else 0)


def latest_run(data):
    runs = data.get("runs") or []
    return runs[-1] if runs else None


# --------------------------------------------------------------------------------------
# Appending a run
# --------------------------------------------------------------------------------------


def append_run(data, record, plan_defects=None, plan_disputes=None, plan_findings=None):
    """Fold one run record into the ledger, and report what it changed.

    ``plan_defects``, ``plan_disputes`` and ``plan_findings`` are the full block bodies from
    the plan, keyed by identifier. The run record carries only the identifiers — it is a
    summary — and the ledger needs the substance, because the ledger is what a later run reads
    instead of the plan.

    Returns a list of human-readable change lines and a list of closure candidates. The
    candidates are printed and **not applied**: see the module docstring.
    """
    plan_defects = plan_defects or {}
    plan_disputes = plan_disputes or {}
    plan_findings = plan_findings or {}

    run_id = _run_id(record)
    changes = []

    if any(entry.get("run_id") == run_id for entry in data["runs"]):
        raise LedgerError(
            f"the ledger already holds a run with id {run_id!r}. Appending it again would "
            "double-count every figure in it. If this is a re-run of the same close-out, the "
            "previous entry is the one to correct; if it is a genuinely new run, it has a new "
            "close commit and therefore a new identifier."
        )

    data["runs"].append({
        "run_id": run_id,
        "closed": record.get("closed"),
        "branch": record.get("branch"),
        "base_commit": record.get("base_commit"),
        "close_commit": record.get("close_commit"),
        "report": record.get("report_path"),
        "plan": record.get("plan_path"),
        "baseline_run": record.get("baseline_run"),
        "commit_distance": record.get("commit_distance"),
        "headline": _headline(record),
    })
    changes.append(f"run {run_id} appended")

    for entry in record.get("decisions") or []:
        data["decisions"].append({
            "run": run_id,
            "id": entry.get("id"),
            "defect": entry.get("defect"),
            "option": entry.get("option"),
            "commit": entry.get("commit"),
        })

    changes += _fold_defects(data, record, run_id, plan_defects)
    changes += _fold_disputes(data, record, run_id, plan_disputes)
    changes += _fold_flags(data, record, run_id)
    changes += _fold_findings(data, record, run_id, plan_findings)
    changes += _fold_scope(data, record, run_id)
    changes += _fold_claims(data, record, run_id)

    data["footprint_accuracy"].append(_footprint_row(record, run_id))

    return changes, closure_candidates(data, record)


def _run_id(record):
    """A run's stable identifier: its close date and its close commit.

    Both halves earn their place. The date is what a person searching the ledger will look
    for; the commit is what makes two close-outs on the same day distinguishable, which the
    fixture repository produces routinely.
    """
    commit = (record.get("close_commit") or record.get("base_commit") or "nocommit")[:7]
    return f"{record.get('closed') or 'undated'}-{commit}"


def _headline(record):
    """The figures a run entry carries, all copied from the record and none recomputed."""
    items = {entry.get("status"): entry.get("count", 0) for entry in record.get("items") or []}
    claims = {entry.get("label"): entry.get("count", 0) for entry in record.get("claims") or []}
    coverage = record.get("coverage") or []
    return {
        "items_total": sum(items.values()),
        "items_by_status": items,
        "claims_by_authority": claims,
        "defects": len(record.get("defects") or []),
        "disputes": len(record.get("disputes") or []),
        "coverage_targets": len(coverage),
        "coverage_targets_met": sum(1 for row in coverage if row.get("met")),
        "narrowings": len(record.get("narrowings") or []),
    }


def _index(entries, key="id"):
    return {entry.get(key): entry for entry in entries if isinstance(entry, dict)}


def _fold_defects(data, record, run_id, plan_defects):
    changes = []
    existing = _index(data["defects"])
    decisions = {
        entry.get("defect"): entry for entry in (record.get("decisions") or [])
        if isinstance(entry, dict)
    }
    # What each close-out answer means for the defect's ledger state. `fix-the-code` and
    # `accept-with-red` both leave it open — the difference between them is who enforces the
    # red, not whether the defect is still real — and that is why both map to `open` rather
    # than to two states nobody could act on differently.
    state_for = {
        "fix-the-code": "open",
        "accept-with-red": "open",
        "requirement-wrong": "requirement-amended",
        "downgrade": "downgraded",
    }

    for defect_id in record.get("defects") or []:
        source = plan_defects.get(defect_id, {})
        decision = decisions.get(defect_id, {})
        state = state_for.get(decision.get("option"), "open")
        entry = existing.get(defect_id)
        if entry is None:
            data["defects"].append({
                "id": defect_id,
                "claim": source.get("claim"),
                "summary": source.get("observed"),
                "test": source.get("test"),
                "locations": list(source.get("locations") or []),
                "state": state,
                "raised_in": run_id,
                "last_seen": run_id,
                "decision": {
                    "option": decision.get("option"),
                    "run": run_id,
                    "commit": decision.get("commit"),
                } if decision else None,
                "fixed_in": None,
                "fixing_commit": None,
            })
            changes.append(f"defect {defect_id} raised, state {state}")
        else:
            entry["last_seen"] = run_id
            if decision:
                entry["decision"] = {
                    "option": decision.get("option"),
                    "run": run_id,
                    "commit": decision.get("commit"),
                }
            if entry.get("state") != state and entry.get("state") == "open":
                entry["state"] = state
                changes.append(f"defect {defect_id} moved to {state}")
            else:
                changes.append(f"defect {defect_id} re-reported, still {entry.get('state')}")
    return changes


def _fold_disputes(data, record, run_id, plan_disputes):
    changes = []
    existing = {entry.get("claim"): entry for entry in data["disputes"]}
    answers = {
        entry.get("claim"): entry for entry in (record.get("dispute_decisions") or [])
        if isinstance(entry, dict)
    }
    for claim_id in record.get("disputes") or []:
        source = plan_disputes.get(claim_id, {})
        answer = answers.get(claim_id)
        state = "corrected" if (answer or {}).get("option") == "correct-the-claim" else "open"
        entry = existing.get(claim_id)
        if entry is None:
            data["disputes"].append({
                "claim": claim_id,
                "summary": source.get("text"),
                "evidence": source.get("evidence"),
                "state": state,
                "raised_in": run_id,
                "last_seen": run_id,
                "corrected_text": (answer or {}).get("corrected-text"),
            })
            changes.append(f"dispute {claim_id} raised, state {state}")
        else:
            entry["last_seen"] = run_id
            if state == "corrected" and entry.get("state") == "open":
                entry["state"] = "corrected"
                entry["corrected_text"] = (answer or {}).get("corrected-text")
                changes.append(f"dispute {claim_id} corrected")
            else:
                changes.append(f"dispute {claim_id} re-reported, still {entry.get('state')}")
    return changes


def _fold_flags(data, record, run_id):
    changes = []
    existing = _index(data["amendment_flags"])
    for flag in record.get("amendment_flags") or []:
        if not isinstance(flag, dict):
            continue
        flag_id = flag.get("id")
        if flag_id in existing:
            existing[flag_id]["last_seen"] = run_id
            changes.append(f"amendment flag {flag_id} re-reported")
            continue
        data["amendment_flags"].append({
            "id": flag_id,
            "document": flag.get("document"),
            "passage": flag.get("passage"),
            "state": "open",
            "raised_in": run_id,
            "last_seen": run_id,
            "resolved_by": None,
        })
        changes.append(f"amendment flag {flag_id} raised against {flag.get('document')}")
    return changes


def _fold_findings(data, record, run_id, plan_findings):
    """R-8.2: a finding that recurs without being retired or contested is flagged as such.

    The recurrence count lives here rather than in the plan because a run cannot know it: the
    plan is one run's document and the count is a property of the sequence. `findings.py`
    reconciles against this before assigning identifiers, so a recurring finding keeps the
    number it was first raised under rather than collecting a new one every run.
    """
    changes = []
    existing = _index(data["findings"])
    for entry in record.get("findings") or []:
        if not isinstance(entry, dict):
            continue
        finding_id = entry.get("id")
        source = plan_findings.get(finding_id, {})
        held = existing.get(finding_id)
        if held is None:
            data["findings"].append({
                "id": finding_id,
                "category": entry.get("category"),
                "summary": source.get("summary"),
                "evidence": source.get("evidence"),
                "state": entry.get("state") or "open",
                "first_seen": run_id,
                "last_seen": run_id,
                "occurrences": 1,
                "retired_by": None,
            })
            changes.append(f"finding {finding_id} raised ({entry.get('category')})")
            continue
        if held.get("state") in ("retired", "contested"):
            changes.append(
                f"finding {finding_id} re-raised while {held.get('state')} — reopened"
            )
            held["state"] = "recurring"
            held["retired_by"] = None
        held["occurrences"] = int(held.get("occurrences") or 1) + 1
        held["last_seen"] = run_id
        if held["occurrences"] >= 2 and held.get("state") == "open":
            held["state"] = "recurring"
            changes.append(
                f"finding {finding_id} is now recurring ({held['occurrences']} runs)"
            )
        else:
            changes.append(f"finding {finding_id} re-reported, {held['occurrences']} runs")
    return changes


def _fold_scope(data, record, run_id):
    """R-6.6: undelivered scope is carried to the ledger rather than blocking closure."""
    changes = []
    existing = _index(data["scope"])
    undelivered = {"failed", "stale", "skipped", "blocked-by-failure", "in-progress", "pending"}
    delivered = set()
    for entry in record.get("items") or []:
        status = entry.get("status")
        ids = entry.get("ids") or []
        if status in ("done", "done-with-defect"):
            delivered.update(ids)
            continue
        if status not in undelivered:
            continue
        for item_id in ids:
            held = existing.get(item_id)
            if held is None:
                data["scope"].append({
                    "id": item_id,
                    "summary": f"{item_id} ended {status} and delivered nothing",
                    "status": status,
                    "state": "open",
                    "raised_in": run_id,
                    "last_seen": run_id,
                    "reason": None,
                })
                changes.append(f"scope {item_id} carried open ({status})")
            else:
                held["last_seen"] = run_id
                held["status"] = status
                changes.append(f"scope {item_id} still {status}")

    for item_id in sorted(delivered):
        held = existing.get(item_id)
        if held is not None and held.get("state") == "open":
            held["state"] = "delivered"
            held["last_seen"] = run_id
            changes.append(f"scope {item_id} delivered")
    return changes


def _fold_claims(data, record, run_id):
    """Every claim with its current authority, which is what R-7.3 holds the planner to."""
    changes = []
    existing = _index(data["claims"])
    for entry in record.get("claims") or []:
        if not isinstance(entry, dict):
            continue
        authority = entry.get("label")
        for claim_id in entry.get("ids") or []:
            held = existing.get(claim_id)
            if held is None:
                data["claims"].append({
                    "id": claim_id,
                    "authority": authority,
                    "first_seen": run_id,
                    "last_seen": run_id,
                })
                changes.append(f"claim {claim_id} recorded at {authority}")
            else:
                if held.get("authority") != authority:
                    changes.append(
                        f"claim {claim_id} moved from {held.get('authority')} to {authority}"
                    )
                held["authority"] = authority
                held["last_seen"] = run_id
    return changes


def _footprint_row(record, run_id):
    """R-8.1's footprint accuracy, accumulated toward planning's R-10.3.

    Stage two deferred concurrent execution until declared footprints are shown to match
    actual ones across real plans. One run is not evidence; this is where the runs accumulate.
    """
    rows = record.get("footprint") or []
    exact = sum(
        1 for row in rows if not row.get("declared_only") and not row.get("actual_only")
    )
    return {
        "run": run_id,
        "items_measured": len(rows),
        "exact": exact,
        "declared_only": sum(1 for row in rows if row.get("declared_only")),
        "actual_only": sum(1 for row in rows if row.get("actual_only")),
    }


_FAILURE_SEPARATORS = re.compile(r"::|\s+>\s+|\s+›\s+|\s*[|]\s*")


def failure_components(entry):
    """Every whole component of a reported failure, plus the whole string.

    A runner names a failure with more than the function: pytest writes
    `tests/test_money_parse.py::test_reads_the_separator`, vitest and jest write
    `file > describe > name`. The defect registry stores the file and the bare name in separate
    fields, so comparing the registry's name against the runner's string as whole strings can
    never match — which made every standing red test look like a fixed one.
    """
    text = (entry or "").strip()
    if not text:
        return set()
    parts = {text}
    for piece in _FAILURE_SEPARATORS.split(text):
        piece = piece.strip()
        if piece:
            parts.add(piece)
    return parts


def still_failing(test, expected):
    """Whether the registry's test is among the runner's reported failures.

    Matches on the bare test name against any whole component of a reported failure. Substring
    matching is deliberately not used: `test_rounds` would match `test_rounds_half_up`, and a
    false match here is the dangerous direction, because it hides a defect that really was
    fixed rather than merely re-reporting one that was not.
    """
    name = (test or {}).get("name")
    if not name:
        return False
    for entry in expected:
        if name in failure_components(entry):
            return True
    return False


def closure_candidates(data, record):
    """Open defects whose red test did not fail in this run, reported and never applied.

    The temptation this resists is worth naming. It would be easy to conclude that a defect is
    fixed because its test was not among the failures, and wrong in the most common case: a run
    whose plan does not touch that area may never execute the test at all, and "did not fail"
    and "passed" are not the same fact. So the inference is offered to a person with its basis
    attached, and only `--close-defect` acts on it.
    """
    suite = record.get("final_suite") or {}
    if not suite.get("measured"):
        return []
    expected = suite.get("expected_failures") or []
    candidates = []
    for entry in data.get("defects", []):
        if entry.get("state") != "open":
            continue
        test = entry.get("test") or {}
        name = test.get("name")
        if name and not still_failing(test, expected):
            candidates.append({
                "id": entry.get("id"),
                "test": name,
                "basis": (
                    "the final suite was measured and this test was not among the expected "
                    "failures. That is consistent with the defect being fixed and also with "
                    "the test not having been run."
                ),
            })
    return candidates


# --------------------------------------------------------------------------------------
# Explicit state changes
# --------------------------------------------------------------------------------------


def close_defect(data, defect_id, commit, evidence, run_id=None):
    entry = _index(data["defects"]).get(defect_id)
    if entry is None:
        raise LedgerError(f"the ledger holds no defect {defect_id!r}")
    if entry.get("state") != "open":
        raise LedgerError(
            f"{defect_id} is {entry.get('state')!r}, not open. Only an open defect closes as "
            "fixed; a downgraded or amended one was disposed of by a decision and reopening it "
            "means contesting that decision, which is a different act with a different record."
        )
    entry["state"] = "fixed"
    entry["fixed_in"] = run_id
    entry["fixing_commit"] = commit
    entry["fix_evidence"] = evidence
    return f"defect {defect_id} closed as fixed at {commit}"


def retire_finding(data, finding_id, by):
    entry = _index(data["findings"]).get(finding_id)
    if entry is None:
        raise LedgerError(f"the ledger holds no pipeline finding {finding_id!r}")
    entry["state"] = "retired"
    entry["retired_by"] = by
    return f"finding {finding_id} retired: {by}"


def resolve_flag(data, flag_id, resolution, note):
    entry = _index(data["amendment_flags"]).get(flag_id)
    if entry is None:
        raise LedgerError(f"the ledger holds no amendment flag {flag_id!r}")
    entry["state"] = resolution
    entry["resolved_by"] = note
    return f"amendment flag {flag_id} {resolution}: {note}"


def contest(data, identifier, note):
    """Mark any open item contested, which is one of the three dispositions R-7.2 permits."""
    for array, key in (
        ("defects", "id"), ("disputes", "claim"), ("amendment_flags", "id"), ("findings", "id"),
    ):
        for entry in data.get(array, []):
            if entry.get(key) == identifier:
                entry["state"] = "contested"
                entry["contested_note"] = note
                return f"{identifier} contested: {note}"
    raise LedgerError(f"the ledger holds no item with identifier {identifier!r}")


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def validate(data):
    """Every state is legal, every identifier unique, and every reference resolves."""
    problems = []
    tables = (
        ("defects", "id", DEFECT_STATES),
        ("disputes", "claim", DISPUTE_STATES),
        ("amendment_flags", "id", FLAG_STATES),
        ("findings", "id", FINDING_STATES),
        ("scope", "id", SCOPE_STATES),
    )
    for array, key, states in tables:
        seen = set()
        for entry in data.get(array, []):
            identifier = entry.get(key)
            if identifier in seen:
                problems.append(f"{array}: {identifier} appears twice")
            seen.add(identifier)
            if entry.get("state") not in states:
                problems.append(
                    f"{array}: {identifier} has state {entry.get('state')!r}, which is not one "
                    f"of {sorted(states)}"
                )
    run_ids = {entry.get("run_id") for entry in data.get("runs", [])}
    for entry in data.get("defects", []):
        if entry.get("raised_in") and entry["raised_in"] not in run_ids:
            problems.append(
                f"defects: {entry.get('id')} was raised in run {entry['raised_in']!r}, which "
                "the ledger does not record"
            )
    for entry in data.get("findings", []):
        if entry.get("state") == "retired" and not entry.get("retired_by"):
            problems.append(
                f"findings: {entry.get('id')} is retired and names nothing that retired it"
            )
    return problems


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def render_open(items):
    if not items:
        return "no open items"
    width = max(len(item["id"] or "") for item in items)
    lines = [f"{len(items)} open item(s):"]
    for item in items:
        # Whitespace collapsed: these summaries come from folded YAML scalars and read back
        # with their line breaks intact, which turns a tidy list into a ragged one.
        summary = " ".join((item["summary"] or "").split())
        lines.append(f"  [{item['kind']:<16}] {(item['id'] or ''):<{width}}  {summary}")
        if item.get("since"):
            lines.append(f"  {'':<18} {'':<{width}}  open since {item['since']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ledger", help="path to docs/test-ledger.json")
    parser.add_argument("--init", action="store_true", help="create an empty ledger")
    parser.add_argument("--repository", help="repository name, for --init")
    parser.add_argument("--open", action="store_true", help="list every open item")
    parser.add_argument("--append", metavar="RUN_RECORD",
                        help="fold a run record JSON file into the ledger")
    parser.add_argument("--plan", help="the plan the run record came from, for --append: the "
                                       "record carries identifiers and the ledger needs the "
                                       "substance behind them")
    parser.add_argument("--close-defect", metavar="ID")
    parser.add_argument("--commit", help="the fixing commit, for --close-defect")
    parser.add_argument("--evidence", help="how the fix was established, for --close-defect")
    parser.add_argument("--retire-finding", metavar="ID")
    parser.add_argument("--by", help="the change that retired it, for --retire-finding")
    parser.add_argument("--amend-flag", metavar="ID")
    parser.add_argument("--contest", metavar="ID")
    parser.add_argument("--note", help="the note accompanying --amend-flag or --contest")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.init:
            if os.path.exists(args.ledger):
                print(f"{args.ledger} already exists; --init would overwrite it",
                      file=sys.stderr)
                return 2
            if not args.repository:
                print("--init needs --repository", file=sys.stderr)
                return 2
            save(args.ledger, empty(args.repository))
            print(f"created {args.ledger} for {args.repository}")
            return 0

        data = load(args.ledger)
        if data is None:
            print(f"no ledger at {args.ledger}. This is the first run against this "
                  "repository; create one with --init.", file=sys.stderr)
            return 2

        changed = False
        messages = []

        if args.append:
            with open(args.append, encoding="utf-8") as handle:
                record = json.load(handle)
            defects, disputes, findings = _plan_substance(args.plan)
            changes, candidates = append_run(data, record, defects, disputes, findings)
            messages += changes
            changed = True
            if candidates:
                messages.append("")
                messages.append(
                    f"{len(candidates)} closure candidate(s) — reported, not applied:"
                )
                for candidate in candidates:
                    messages.append(f"  {candidate['id']} ({candidate['test']})")
                    messages.append(f"    {candidate['basis']}")
                    messages.append(
                        f"    close it with: --close-defect {candidate['id']} --commit <sha> "
                        "--evidence <how you established it>"
                    )

        if args.close_defect:
            if not args.commit or not args.evidence:
                print("--close-defect needs --commit and --evidence: R-7.5 closes a defect "
                      "with the fixing commit, and a closure with no evidence is an "
                      "assertion", file=sys.stderr)
                return 2
            messages.append(close_defect(
                data, args.close_defect, args.commit, args.evidence,
                (latest_run(data) or {}).get("run_id"),
            ))
            changed = True

        if args.retire_finding:
            if not args.by:
                print("--retire-finding needs --by: R-8.2 retires a finding only with the "
                      "change that addressed it named", file=sys.stderr)
                return 2
            messages.append(retire_finding(data, args.retire_finding, args.by))
            changed = True

        if args.amend_flag:
            if not args.note:
                print("--amend-flag needs --note", file=sys.stderr)
                return 2
            messages.append(resolve_flag(data, args.amend_flag, "amended", args.note))
            changed = True

        if args.contest:
            if not args.note:
                print("--contest needs --note: contesting is one of the three dispositions "
                      "R-7.2 permits and it carries evidence like the other two",
                      file=sys.stderr)
                return 2
            messages.append(contest(data, args.contest, args.note))
            changed = True

        if changed:
            problems = validate(data)
            if problems:
                print("the change was not written; it would leave the ledger inconsistent:",
                      file=sys.stderr)
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                return 1
            save(args.ledger, data)

        for message in messages:
            print(message)

        if args.validate:
            problems = validate(data)
            if problems:
                print(f"FAILED: {args.ledger} — {len(problems)} problem(s)")
                for problem in problems:
                    print(f"  {problem}")
                return 1
            print(f"ok: {args.ledger} — {len(data['runs'])} run(s), "
                  f"{len(open_items(data))} open item(s)")

        if args.open or args.json:
            items = open_items(data)
            print(json.dumps(items, indent=2, ensure_ascii=False) if args.json
                  else render_open(items))
    except LedgerError as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 2
    return 0


def _plan_substance(plan_path):
    """The defect, dispute, and finding bodies out of a plan, for --append.

    Optional: without it the ledger records identifiers and states but not the prose, which is
    enough for reconciliation and thin for a person reading the ledger directly.
    """
    if not plan_path:
        return {}, {}, {}
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import siblings  # noqa: PLC0415

    planlib = siblings.planlib()
    by_kind, _, _ = planlib.load_plan(plan_path)
    claims = {
        b.node.get("id"): planlib.to_plain(b.node) for b in by_kind.get("claim", [])
    }
    defects = {}
    for block in by_kind.get("defect", []):
        node = planlib.to_plain(block.node)
        # The production locations the defect is about, copied from its claim. The registry
        # entry names the test rather than the code, and the planner's consistency rule needs
        # the code: it asks whether a future work item touches a file where something is
        # already known to be broken.
        claim = claims.get(node.get("claim")) or {}
        node["locations"] = list(claim.get("locations") or [])
        defects[node.get("id")] = node
    disputes = {
        b.node.get("id"): planlib.to_plain(b.node)
        for b in by_kind.get("claim", [])
        if b.node.get("label") == "disputed"
    }
    findings = {
        b.node.get("id"): planlib.to_plain(b.node)
        for b in by_kind.get("pipeline-finding", [])
    }
    return defects, disputes, findings


if __name__ == "__main__":
    sys.exit(main())

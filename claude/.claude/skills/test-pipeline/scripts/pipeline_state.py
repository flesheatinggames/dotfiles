#!/usr/bin/env python3
"""Where the run stands, derived from the artifacts and nothing else (R-4.1).

This is the whole of the orchestrator's determinism. It reads the assessment report, the plan,
the close-out sheet, the report and the run ledger, runs the four stages' own validators
against them, and returns one position, the condition blocking it, and the single next action.

**It adds no validator of its own.** The preamble to Section 6 of the orchestrator
requirements forbids it, and the reason is the one the whole suite is built on: a second
opinion about whether an artifact is valid is a second opinion that drifts. Every verdict here
comes from `check_index.py`, `read_assessment.py`, `plan_lint.py`, `preflight.py`,
`run_record.py`, `closeout.py`, `trace_report.py`, `ledger.py` or `reconcile.py`. What this
module contributes is the *order* the questions are asked in, which is the one thing none of
those scripts knows.

**Validators are run as subprocesses rather than imported and called.** R-8.1 requires a
stage's diagnosis to be relayed verbatim, and a diagnosis reconstructed from a caught exception
is not verbatim — it is the same text re-worded by the orchestrator, which is exactly what that
requirement forbids. So each check captures the script's own bytes, and the relay is a copy
rather than a paraphrase.

**Nothing here is written to disk.** R-10.2: the orchestrator writes nothing durable, so this
script prints and exits. `--checksums` in particular hashes the artifacts and holds nothing;
comparing a before-set with an after-set is the caller's job, which is what keeps R-9.1
checkable rather than only asserted.

Usage:
    python3 pipeline_state.py --repo .                     # the diagnosis, in prose
    python3 pipeline_state.py --repo . --json              # the same, as data
    python3 pipeline_state.py --repo . --checksums         # one hash per artifact
    python3 pipeline_state.py --selftest                   # every position, from the fixtures
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

import siblings

# --------------------------------------------------------------------------------------
# Artifact locations. Every stage defaults to these and the orchestrator inherits them
# rather than choosing; a fifth opinion about where the plan lives is a fifth place to
# update when it moves.
# --------------------------------------------------------------------------------------

DEFAULT_ASSESSMENT = "docs/test-assessment.md"
DEFAULT_PLAN = "docs/test-plan.md"
DEFAULT_LEDGER = "docs/test-ledger.json"
DEFAULT_SHEET = "docs/test-closeout.md"
DEFAULT_REPORT = "docs/test-report.md"

ARTIFACTS = (
    ("assessment", DEFAULT_ASSESSMENT),
    ("plan", DEFAULT_PLAN),
    ("ledger", DEFAULT_LEDGER),
    ("closeout_sheet", DEFAULT_SHEET),
    ("report", DEFAULT_REPORT),
)

POSITIONS = (
    "not-a-repository",
    "no-assessment",
    "assessment-invalid",
    "no-plan",
    "plan-invalid",
    "awaiting-approval",
    "ready-to-execute",
    "execution-incomplete",
    "executed",
    "awaiting-closeout",
    "closeout-answered",
    "closed",
)

GATES = {"awaiting-approval": "G1", "awaiting-closeout": "G2"}

# The two statuses a planner is allowed to write. Every other value in `planlib.STATUSES` is
# one only the executor writes, which is what makes their presence evidence that a run started.
#
# This distinction is the whole of how `execution-incomplete` is detected, and getting it wrong
# is not a subtle failure: asking merely whether an item carries *a* status reports every
# freshly written plan as an interrupted run, because a planned item carries `status: pending`.
PLANNER_WRITTEN_STATUSES = {"pending", "blocked-on-decision"}

# Which stage owns a plan phase, so that a failing lint names the stage that can repair it
# rather than always naming the planner. A plan that does not lint at `--phase executed` is
# stage three's writeback being wrong, and telling the owner to re-run planning would be
# advice that destroys the run's record.
PHASE_OWNER = {
    "planned": "test-planning",
    "reviewed": "test-planning",
    "executed": "test-execution",
    "closed": "test-reporting",
}


class Check:
    """One validator run, kept whole so R-8.1's verbatim relay has something to copy."""

    def __init__(self, name, command, returncode, stdout, stderr):
        self.name = name
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def output(self):
        """Everything the check said, in the order a terminal would have shown it."""
        return (self.stdout + ("\n" if self.stdout and self.stderr else "") + self.stderr).strip()

    def as_dict(self):
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "output": self.output,
        }


def run_check(name, script_path, arguments, cwd):
    """Run one sibling script and keep every byte of what it said."""
    command = [sys.executable, script_path, *arguments]
    try:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=900
        )
    except subprocess.TimeoutExpired:
        return Check(name, command, 124, "", f"{name} did not finish within 900 seconds")
    except OSError as error:
        return Check(name, command, 127, "", f"{name} could not be run: {error}")
    return Check(name, command, completed.returncode, completed.stdout, completed.stderr)


# --------------------------------------------------------------------------------------
# Reading the artifacts
# --------------------------------------------------------------------------------------


def is_git_repository(repo):
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, text=True
        )
    except OSError:
        return False
    return completed.returncode == 0


def head_commit(repo):
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def read_index(path):
    """The assessment's machine-readable index, or None when there is not one.

    Parsed here rather than through `check_index.py` because this reader must not fail on a
    report the checker rejects: the drift flag wants the assessed commit even out of an index
    that is invalid for some unrelated reason, and a checker that has already said no has
    nothing left to hand back.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(r"```json assessment-index\n(.*?)\n```", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def load_plan_blocks(path):
    """Every block in the plan, indexed by kind, without linting anything.

    `planlib.load_plan` rather than `planio.Plan`, because `planio.Plan` lints on construction
    and this reader is used at positions where the plan is expected not to lint. Reading a
    broken plan is exactly what a diagnosis of a broken plan requires.
    """
    planlib = siblings.planlib()
    by_kind, problems, text = planlib.load_plan(path)
    return by_kind, problems, text


def single_node(by_kind, kind):
    blocks = by_kind.get(kind) or []
    return blocks[0].node if blocks and blocks[0].node else None


def nodes_by_id(by_kind, kind):
    out = {}
    for block in by_kind.get(kind) or []:
        node = block.node or {}
        identifier = node.get("id")
        if isinstance(identifier, str):
            out[identifier] = node
    return out


# --------------------------------------------------------------------------------------
# The two signals that are not positions
# --------------------------------------------------------------------------------------


def drift_flag(repo, index, plan_meta, record):
    """R-8.3: name the commits that disagree and the stage whose revalidation decides.

    Drift is surfaced and never adjudicated. What this returns is a list of disagreements,
    each naming both commits and the stage that will decide what the disagreement costs —
    because that stage's own revalidation is the thing with the authority to price it, and the
    orchestrator has no basis on which to say a drift is harmless.
    """
    flags = []
    head = head_commit(repo)
    assessed = (index or {}).get("commit")
    planned_against = (plan_meta or {}).get("assessment_commit")

    def short(value):
        return value[:7] if isinstance(value, str) and len(value) > 7 else value

    if assessed and planned_against and not _same_commit(assessed, planned_against):
        flags.append({
            "between": "the assessment and the plan",
            "recorded": {"assessment": short(assessed), "plan": short(planned_against)},
            "deciding_stage": "test-planning",
            "decided_by": (
                "the planning stage's own input checks, which read the assessment the plan "
                "declares it was built from"
            ),
        })

    if assessed and head and not _same_commit(assessed, head):
        flags.append({
            "between": "the assessment and the repository",
            "recorded": {"assessment": short(assessed), "HEAD": short(head)},
            "deciding_stage": "test-execution",
            "decided_by": (
                "stage three's pre-flight, which measures commit drift and marks the work "
                "items whose targets moved `stale`"
            ),
        })

    base = (record or {}).get("base_commit")
    if base and head and not _same_commit(base, head):
        flags.append({
            "between": "the run's base commit and the repository",
            "recorded": {"run_base": short(base), "HEAD": short(head)},
            "deciding_stage": "test-reporting",
            "decided_by": (
                "stage four's run record, which measures the run from its base commit to its "
                "close commit rather than to HEAD, so ordinary work on the branch after a "
                "close-out does not make a finished record report itself inconsistent"
            ),
        })

    return flags


def _same_commit(left, right):
    """Two commit references agree when one is a prefix of the other.

    The artifacts do not agree about abbreviation: the assessment index records seven
    characters and the run record records forty. Comparing them for equality would report
    drift on every repository that has none.
    """
    if not left or not right:
        return False
    shorter, longer = sorted((left, right), key=len)
    return longer.startswith(shorter)


def open_run_flag(repo, plan_path, ledger_path, record, closed_lint_ok):
    """R-4.4, derived from content rather than from file recency.

    A run is open when a plan file exists that either no ledger entry names, or that a ledger
    entry names but which does not lint clean at `--phase closed`.

    "Names" is answered two ways, and the fallback is not optional. A ledger run entry carries
    a `plan` field, but neither the fixture ledger nor `design-os`'s real one has it — both
    predate the field — so a derivation that asked only that question would report an open run
    on a repository whose only run is closed. The second question is the durable one: the
    plan's own run-record block carries the close date and the close commit, which is exactly
    what the ledger computes its `run_id` from, so the two can be matched without either side
    storing a path.
    """
    if not os.path.isfile(os.path.join(repo, plan_path)):
        return {"open": False, "why": "there is no plan, so there is no run to be open"}

    if not os.path.isfile(os.path.join(repo, ledger_path)):
        return {
            "open": True,
            "why": (
                "a plan exists and the repository has no run ledger, so no entry can name it"
            ),
        }

    try:
        with open(os.path.join(repo, ledger_path), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        return {
            "open": True,
            "why": f"a plan exists and the run ledger could not be read ({error})",
        }

    named_by = None
    for entry in data.get("runs") or []:
        if entry.get("plan") and _same_path(entry["plan"], plan_path):
            named_by = entry.get("run_id")
            break
        if record and entry.get("run_id") == derived_run_id(record):
            named_by = entry.get("run_id")
            break

    if named_by is None:
        return {
            "open": True,
            "why": "a plan exists and no run entry in the ledger names it",
        }
    if not closed_lint_ok:
        return {
            "open": True,
            "named_by": named_by,
            "why": (
                f"run {named_by} names this plan, but the plan does not lint clean at "
                "`--phase closed`"
            ),
        }
    return {
        "open": False,
        "named_by": named_by,
        "why": f"run {named_by} names this plan and the plan lints clean at `--phase closed`",
    }


def _same_path(left, right):
    return os.path.normpath(left) == os.path.normpath(right)


def derived_run_id(record):
    """The run identifier the ledger would compute from this plan's own run-record block.

    Deliberately the same arithmetic as `ledger._run_id`, and deliberately not an import of
    it: that function takes the record dictionary stage four assembles, and what is available
    here is the block in the plan. The two carry the same two fields under the same two names,
    which is what makes the match sound.
    """
    if not record:
        return None
    commit = (record.get("close_commit") or record.get("base_commit") or "nocommit")[:7]
    return f"{record.get('closed') or 'undated'}-{commit}"


# --------------------------------------------------------------------------------------
# The derivation
# --------------------------------------------------------------------------------------


def _run_is_closed(repo, diagnosis, plan, assessment, ledger, report, has_ledger):
    """The four conditions for `closed`, gathered once and cached on the diagnosis.

    Gathered here rather than inline because the answer is needed twice and at opposite ends
    of the walk: once up front, to decide whether the assessment still owes the ledger a
    reconciliation, and once at the end, to settle the position. Running the four checks twice
    would be wasteful and — worse — would make the two answers separately derived, so a check
    that was not deterministic could have the walk decide the run was closed at the top and
    not closed at the bottom.
    """
    full = os.path.join(repo, plan)
    if not os.path.isfile(full):
        diagnosis.closed_evidence = None
        return False

    by_kind, _, _ = load_plan_blocks(full)
    record = single_node(by_kind, "run-record")
    if not record:
        diagnosis.closed_evidence = None
        return False

    # No `--ledger` at this phase, and it is not an oversight. The linter's ledger rules bind
    # the plan of the *next* run, and it says so itself: handed the plan that produced the
    # ledger's latest run it reports `ledger-is-this-plans-own`, skips the rules, and exits
    # non-zero. That verdict is correct and it is not a lint failure — but it is indexed as
    # one, so passing the flag here would make every closed run report its own plan as broken.
    #
    # The orchestrator cannot avoid this by checking first, because whether this plan is the
    # one that built the ledger is the very question being answered. The phase settles it
    # instead: a plan linted at `closed` is by definition the run that just closed.
    closed_check = diagnosis.record(run_check(
        "plan_lint.py --phase closed", siblings.path_of("test-planning", "plan_lint.py"),
        [plan, "--assessment", assessment, "--phase", "closed"],
        repo,
    ))
    report_exists = os.path.isfile(os.path.join(repo, report))
    trace_check = None
    if report_exists:
        trace_check = diagnosis.record(run_check(
            "trace_report.py", siblings.path_of("test-reporting", "trace_report.py"),
            [report, "--repo", ".", "--plan", plan, "--phase", "closed"]
            + (["--ledger", ledger] if has_ledger else []),
            repo,
        ))
    open_run = open_run_flag(repo, plan, ledger, record, closed_check.ok)

    diagnosis.closed_evidence = {
        "record": record,
        "closed_check": closed_check,
        "report_exists": report_exists,
        "trace_check": trace_check,
        "open_run": open_run,
    }
    return bool(
        closed_check.ok and report_exists and trace_check.ok and open_run.get("named_by")
    )


class Diagnosis:
    """One position, why it is blocked, and the one next action. Nothing else."""

    def __init__(self, repo, paths):
        self.repo = repo
        self.paths = paths
        self.position = None
        self.blocking = None
        self.next_action = None
        self.next_stage = None
        self.gate = None
        self.checks = []
        self.relay = None
        self.notes = []
        self.drift = []
        self.open_run = {}
        self.brief_data = {}
        self.closed_evidence = None

    def record(self, check):
        self.checks.append(check)
        return check

    def settle(self, position, blocking, next_action, next_stage=None, relay=None):
        self.position = position
        self.blocking = blocking
        self.next_action = next_action
        self.next_stage = next_stage
        self.gate = GATES.get(position)
        self.relay = relay
        return self

    def as_dict(self):
        return {
            "repository": self.repo,
            "paths": self.paths,
            "position": self.position,
            "gate": self.gate,
            "blocking": self.blocking,
            "next_action": self.next_action,
            "next_stage": self.next_stage,
            "relay": self.relay,
            "notes": self.notes,
            "drift": self.drift,
            "open_run": self.open_run,
            "brief_data": self.brief_data,
            "checks": [check.as_dict() for check in self.checks],
        }


def derive(repo, assessment=DEFAULT_ASSESSMENT, plan=DEFAULT_PLAN, ledger=DEFAULT_LEDGER,
           sheet=DEFAULT_SHEET, report=DEFAULT_REPORT):
    """Walk the pipeline forward and stop at the first precondition that does not hold.

    Forward rather than backward, because that is what a ratchet is: the position is the first
    place the run cannot advance from, and asking the questions in pipeline order is what makes
    the answer the same every time.
    """
    paths = {
        "assessment": assessment, "plan": plan, "ledger": ledger,
        "closeout_sheet": sheet, "report": report,
    }
    diagnosis = Diagnosis(repo, paths)

    def full(relative):
        return os.path.join(repo, relative)

    # ---- R-6.1: the target is a git repository ---------------------------------------
    if not is_git_repository(repo):
        return diagnosis.settle(
            "not-a-repository",
            f"{repo} is not a git repository, or git is not available here",
            "Tell the owner. Every stage past the assessment records commits, measures drift "
            "against them, and works on a branch, so there is nothing the pipeline can do "
            "here. Run `git init` and commit the code first, or point the pipeline at the "
            "repository root.",
        )

    has_ledger = os.path.isfile(full(ledger))

    # ---- R-6.2, first half: the assessment exists ------------------------------------
    if not os.path.isfile(full(assessment)):
        mode = "reconciliation" if has_ledger else "fresh"
        why = (
            f"`{ledger}` exists, so stage one's Step 7d runs and every open ledger item must "
            "be confirmed, updated, or contested in the new report"
            if has_ledger else
            f"there is no `{ledger}`, so stage one's Step 7d is skipped entirely and this is "
            "a first assessment of the repository"
        )
        diagnosis.notes.append(f"Stage one runs in {mode} mode, because {why}.")
        return diagnosis.settle(
            "no-assessment",
            f"there is no assessment report at `{assessment}`",
            f"Invoke the `test-assessment` skill against {repo}. It selects {mode} mode "
            "itself on the presence of the run ledger; the orchestrator passes no mode flag "
            "and has none to pass.",
            next_stage="test-assessment",
        )

    index = read_index(full(assessment))

    # ---- Is this repository's current run already closed? ----------------------------
    #
    # Asked before the assessment is validated, and only because of the ledger. **Closing a
    # run for the first time makes that run's own assessment fail the reconciliation check**,
    # because the assessment was written when there was no ledger and `check_index.py
    # --ledger` requires every open ledger item to be confirmed, updated, or contested. Every
    # first close-out produces that state, and `design-os` is sitting in it.
    #
    # Reading it as a failure would be wrong twice over. It would report a correctly closed
    # run as having a broken assessment, and it would send the owner to backfill a document
    # whose job is finished. R-7.2's obligation falls on the assessment that *begins the next
    # run*, not on the one that began this one — the next assessment inherits the ledger and
    # must answer for it, which is the whole of the bargain R-7.4 offers in return.
    #
    # This is the same shape as two defects the project has already been bitten by: the run
    # record that measured to HEAD, so an ordinary commit after close-out made a finished
    # record report itself inconsistent, and the assembler that read the ledger's latest run
    # as its own baseline, so a re-run named itself as its own predecessor. All three are a
    # closed thing being re-judged against a world that has moved on since it closed.
    run_is_closed = _run_is_closed(repo, diagnosis, plan, assessment, ledger, report,
                                   has_ledger)

    # ---- R-6.2, second half: the index validates under the assessment's own checker ---
    check_index_args = [assessment]
    if has_ledger and not run_is_closed:
        check_index_args += ["--ledger", ledger]
    index_check = diagnosis.record(run_check(
        "check_index.py", siblings.path_of("test-assessment", "check_index.py"),
        check_index_args, repo,
    ))

    reader_check = diagnosis.record(run_check(
        "read_assessment.py", siblings.path_of("test-planning", "read_assessment.py"),
        [assessment, "--json"], repo,
    ))

    if not index_check.ok or not reader_check.ok:
        failing = index_check if not index_check.ok else reader_check
        return diagnosis.settle(
            "assessment-invalid",
            f"`{failing.name}` rejects `{assessment}`",
            "Relay the diagnosis below verbatim and stop. The remedy is stage one's, and it "
            "is a backfill rather than a re-assessment: nothing is re-measured. Invoke the "
            "`test-assessment` skill in backfill mode once the owner has read it.",
            next_stage="test-assessment",
            relay=failing.output,
        )

    if index and index.get("verification") == "skipped":
        diagnosis.notes.append(
            "The assessment records its verification pass as `skipped`, which is a legal "
            "value and advances the pipeline. It is a degradation rather than a failure, and "
            "it belongs in the gate one brief: every finding in that report is "
            "single-sourced, so the owner approves the plan knowing no second reader checked "
            "the map it was built from."
        )

    if has_ledger and not run_is_closed:
        reconcile_check = diagnosis.record(run_check(
            "reconcile.py", siblings.path_of("test-reporting", "reconcile.py"),
            [ledger, assessment], repo,
        ))
        if not reconcile_check.ok:
            return diagnosis.settle(
                "assessment-invalid",
                f"`{assessment}` does not reconcile every open item in `{ledger}`",
                "Relay the diagnosis below verbatim and stop. An open ledger item the "
                "assessment does not confirm, update, or contest is the one failure nothing "
                "else in the pipeline can catch, because a dropped item leaves no trace to "
                "catch. Stage one's Step 7d is where it is answered.",
                next_stage="test-assessment",
                relay=reconcile_check.output,
            )

    plan_meta = None
    record = None

    # ---- R-6.3: the plan exists ------------------------------------------------------
    if not os.path.isfile(full(plan)):
        diagnosis.drift = drift_flag(repo, index, None, None)
        diagnosis.open_run = open_run_flag(repo, plan, ledger, None, False)
        return diagnosis.settle(
            "no-plan",
            f"there is no plan at `{plan}`",
            f"Invoke the `test-planning` skill against {repo}, giving it `{assessment}` and "
            "the repository. It reads the index mechanically and everything else as prose.",
            next_stage="test-planning",
        )

    by_kind, parse_problems, _ = load_plan_blocks(full(plan))
    plan_meta = single_node(by_kind, "plan-meta")
    record = single_node(by_kind, "run-record")
    summary = single_node(by_kind, "run-summary")
    items = nodes_by_id(by_kind, "work-item")
    defects = nodes_by_id(by_kind, "defect")
    approved = bool((plan_meta or {}).get("approved"))
    executor_statuses = sorted({
        node.get("status") for node in items.values()
        if node.get("status") and node["status"] not in PLANNER_WRITTEN_STATUSES
    })

    def lint(phase):
        # `--ledger` is dropped at the closed phase; see `_run_is_closed` for why. At the
        # three earlier phases the ledger belongs to a previous run and its rules are exactly
        # what should be checked.
        with_ledger = has_ledger and phase != "closed"
        return diagnosis.record(run_check(
            f"plan_lint.py --phase {phase}",
            siblings.path_of("test-planning", "plan_lint.py"),
            [plan, "--assessment", assessment, "--phase", phase]
            + (["--ledger", ledger] if with_ledger else []),
            repo,
        ))

    def invalid(phase, check):
        owner = PHASE_OWNER[phase]
        remedy = {
            "test-planning": (
                "Relay the lint output below verbatim. Repairing a plan is stage two's work; "
                "the orchestrator never edits one."
            ),
            "test-execution": (
                "Relay the lint output below verbatim. This is stage three's writeback of "
                "what happened during the run, so the repair is not a re-plan — re-running "
                "planning would replace the record of a run that already happened. Treat a "
                "failure here as a pipeline finding about stage three."
            ),
            "test-reporting": (
                "Relay the lint output below verbatim. The close-out records are stage four's "
                "and the repair is stage four's."
            ),
        }[owner]
        return diagnosis.settle(
            "plan-invalid",
            f"`{plan}` does not lint clean at `--phase {phase}`",
            remedy,
            next_stage=owner,
            relay=check.output,
        )

    # ---- Close-out territory. Asked first because a closed run leaves every earlier
    # ---- artifact in place, and asking the earlier questions first would find them.
    #
    # The four checks behind it already ran, at the top of the walk, because whether the run
    # is closed decides whether the assessment still owes the ledger a reconciliation. They
    # are read back here rather than re-run.
    evidence = diagnosis.closed_evidence or {}
    closed_check = evidence.get("closed_check")
    closed_ok = bool(closed_check and closed_check.ok)

    diagnosis.drift = drift_flag(repo, index, plan_meta, record)
    diagnosis.open_run = evidence.get("open_run") or open_run_flag(
        repo, plan, ledger, record, closed_ok
    )

    if record:
        report_exists = evidence.get("report_exists", False)
        trace_check = evidence.get("trace_check")
        ledger_names_run = bool(diagnosis.open_run.get("named_by"))

        if closed_ok and report_exists and trace_check.ok and ledger_names_run:
            diagnosis.brief_data = {
                "run_id": diagnosis.open_run.get("named_by"),
                "branch": record.get("branch"),
                "close_commit": record.get("close_commit"),
                "report": report,
            }
            return diagnosis.settle(
                "closed",
                None,
                "The branch is settled. State what each close-out decision did to it, what "
                "the ledger now holds open, and hand the owner the merge instruction. "
                "**The orchestrator never merges** (R-9.4).",
            )

        if not closed_ok:
            return invalid("closed", closed_check)
        if not report_exists:
            return diagnosis.settle(
                "closeout-answered",
                f"the close-out is applied and there is no report at `{report}`",
                "Invoke the `test-reporting` skill for its post-gate segment. The answers are "
                "already applied, so it resumes at its Step 3: assemble the record and the "
                "findings, write the report, run the plain-language reader, append the "
                "ledger.",
                next_stage="test-reporting",
            )
        if not trace_check.ok:
            return diagnosis.settle(
                "closeout-answered",
                f"`{report}` does not trace against the run record",
                "Relay the tracer's output below verbatim. It regenerates the report from the "
                "record and proves every generated region is byte-identical, then traces every "
                "number in the prose. Both halves are stage four's to repair, and **never by "
                "adding a figure to the record** — a number put there by hand is a number "
                "nobody computed wearing the record's authority.",
                next_stage="test-reporting",
                relay=trace_check.output,
            )
        return diagnosis.settle(
            "closeout-answered",
            f"the run is not named by any entry in `{ledger}`",
            "Invoke the `test-reporting` skill to finish its Step 6: append the run record to "
            "the ledger. Until that happens the next assessment inherits no obligations from "
            "this run.",
            next_stage="test-reporting",
        )

    # ---- Gate two. The sheet exists and the run record does not. ----------------------
    #
    # The sheet is a file on disk while every other signal in this walk is a block inside the
    # plan, and the pipeline reuses one path per artifact across runs. So a sheet left by the
    # previous run outlives the plan it belongs to, and testing only for its presence hands a
    # freshly written, never-approved plan to the post-gate segment — which would apply that
    # stale sheet, assemble a report from a run record that does not exist, and append the
    # ledger. The sheet is only this run's if this plan has actually been executed.
    if os.path.isfile(full(sheet)) and (summary or executor_statuses):
        answered, unanswered, sheet_problems = read_sheet_state(full(plan), full(sheet), defects)
        diagnosis.brief_data = {
            "sheet": sheet,
            "defects_total": len(defects),
            "defects_answered": answered,
            "defects_unanswered": unanswered,
            "empty_gate": not defects,
        }
        if sheet_problems:
            return diagnosis.settle(
                "awaiting-closeout",
                f"`{sheet}` is not completely answered",
                "Write the gate two brief and stop. The gate is one sitting and a partially "
                "answered sheet is refused rather than half-applied, so the run stays open "
                "until every defect carries a complete answer. **Never fill one in** — one of "
                "the four options makes a real failure stop being visible, and it is "
                "available to nobody but the owner.",
                relay="\n".join(sheet_problems),
            )
        if not defects:
            diagnosis.notes.append(
                "The gate is empty: this run registered no defects, so the sheet's body is a "
                "`No defects` section. An empty gate does not stop the ratchet and is still "
                "applied — the run closes by running `--apply` over the empty sheet, which is "
                "what writes the records the closed phase requires."
            )
        return diagnosis.settle(
            "closeout-answered",
            None,
            "Invoke the `test-reporting` skill for its post-gate segment: apply the answers, "
            "assemble the record and the findings, write the report, run the plain-language "
            "reader, and append the ledger.",
            next_stage="test-reporting",
        )

    # ---- R-6.5: execution ended ------------------------------------------------------
    if summary:
        executed_check = lint("executed")
        if not executed_check.ok:
            return invalid("executed", executed_check)
        record_check = diagnosis.record(run_check(
            "run_record.py --no-suite", siblings.path_of("test-reporting", "run_record.py"),
            [plan, "--repo", ".", "--assessment", assessment, "--no-suite"]
            + (["--ledger", ledger] if has_ledger else []),
            repo,
        ))
        diagnosis.brief_data = {
            "items": summary.get("items"),
            "defects": sorted(defects),
            "partial": bool(summary.get("narrowings")),
        }
        if not record_check.ok:
            diagnosis.notes.append(
                "Stage four's own input verification reports failures against this run. They "
                "are not a blocker: R-6.5 makes a partial-and-honest run a pipeline success "
                "mode, and each failed check is a pipeline finding that stage four records "
                "and that degrades the report's stated confidence. **Read them rather than "
                "repairing them** — editing the run summary to make a check pass destroys the "
                "only evidence that the pipeline has a gap."
            )
        return diagnosis.settle(
            "executed",
            None,
            "Invoke the `test-reporting` skill for its pre-gate segment: read the run and "
            "write the close-out decision sheet. It stops there, and so does the ratchet if "
            "the sheet holds a defect.",
            next_stage="test-reporting",
        )

    # ---- The one state the orchestrator may only relay -------------------------------
    #
    # Approval is part of the recognition test and not an incidental extra condition. Stage
    # three's pre-flight refuses to start on an unapproved plan, so executor-written statuses
    # on one cannot be the residue of an interrupted run — no run could have begun. They are a
    # malformed plan, which is a different position with a different remedy, and without this
    # clause the deliberately broken fixture (unapproved, one illegal `status: done`) reports
    # as an interrupted run and the owner is told to go and resolve a run that never happened.
    if approved and executor_statuses:
        diagnosis.brief_data = {"statuses_written": executor_statuses}
        return diagnosis.settle(
            "execution-incomplete",
            "the plan is approved and work items carry statuses only the executor writes ("
            + ", ".join(executor_statuses)
            + "), and the plan holds no run summary, so a run started and did not finish",
            "Relay stage three's stop and choose nothing. Resuming an interrupted run is not "
            "implemented, deliberately: pre-flight names the two supported ways forward and "
            "refuses to pick between them **because one of them destroys work**. That choice "
            "is the owner's, and it is not one the orchestrator is permitted to make on their "
            "behalf (R-9.2). Run stage three's pre-flight to print the two options in its own "
            "words, and add nothing to them.",
            next_stage="test-execution",
        )

    # ---- Gate one --------------------------------------------------------------------
    if approved:
        diagnosis.brief_data = {
            "approved_by": (plan_meta or {}).get("approved"),
            "target_approved": bool(single_node(by_kind, "target") or {}),
        }
        return diagnosis.settle(
            "ready-to-execute",
            None,
            "Invoke the `test-execution` skill. Its pre-flight establishes everything between "
            "approval and the first work item — the `--phase reviewed` lint, the applied "
            "option rewrites, the skipped items of unresolved decisions, the clean working "
            "tree, the commit drift — and is the final arbiter. The orchestrator invokes it "
            "rather than anticipating it, and relays whatever it says.",
            next_stage="test-execution",
        )

    planned_check = lint("planned")
    if planned_check.ok:
        return _await_approval(diagnosis, plan, "planned")

    reviewed_check = lint("reviewed")
    if reviewed_check.ok:
        diagnosis.notes.append(
            "The plan lints clean at `--phase reviewed` and not at `--phase planned`, which "
            "means the owner's review sitting has started: resolutions or ratifications are "
            "written in and approval is not. That is a legal state and the gate is still open."
        )
        return _await_approval(diagnosis, plan, "reviewed")

    if parse_problems:
        diagnosis.notes.append(
            f"The plan does not fully parse: {len(parse_problems)} structural problem(s) "
            "before any rule was applied."
        )
    return invalid("planned", planned_check)


def _await_approval(diagnosis, plan, phase):
    diagnosis.brief_data = {"lints_clean_at": phase}
    return diagnosis.settle(
        "awaiting-approval",
        f"`{plan}` records no `approved` field under `plan-meta`",
        "Write the gate one brief and stop. Plan approval is the owner's act and nothing "
        "derives it, so every fresh run reaches this gate and halts. Use `gate_brief.py "
        "--gate 1` for the escalations, the decisions and their options, the ratification "
        "list and its size, the target proposal, and where each answer is recorded. **Never "
        "add the field on the owner's behalf, and never recommend an answer** (R-9.2).",
    )


def read_sheet_state(plan_path, sheet_path, defects):
    """How much of the close-out sheet is answered, judged by stage four's own validator.

    `closeout.validate_answers` is the thing that decides whether an answer is complete, and it
    decides it strictly: a missing decider, a rationale under thirty characters, a
    `requirement-wrong` with no amendment flag, or an automated-looking name against a
    `downgrade` all fail. Re-implementing any of that here would be a second standard for what
    an answered gate is, and the orchestrator would then let through a sheet stage four is
    about to refuse.
    """
    import gate_brief  # noqa: PLC0415 - same skill, imported here to keep the counting in one place

    closeout = siblings.closeout()
    planio = siblings.planio()
    try:
        plan = planio.Plan(plan_path, phase="closed", lint_writes=False)
    except Exception as error:  # noqa: BLE001 - the message is relayed, not swallowed
        return 0, len(defects), [f"the plan could not be read: {error}"]
    try:
        answers, _ = closeout.read_sheet(sheet_path)
    except closeout.CloseoutError as error:
        return 0, len(defects), [str(error)]
    problems = closeout.validate_answers(plan, answers, sheet_path)
    answered = gate_brief.answered_defects(sorted(defects), answers, problems)
    return len(answered), len(defects) - len(answered), problems


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def render(diagnosis):
    lines = []
    add = lines.append
    add(f"position: {diagnosis.position}")
    if diagnosis.gate:
        add(f"gate: {diagnosis.gate} — the pipeline cannot advance without the owner")
    add(f"repository: {diagnosis.repo}")
    add("")
    if diagnosis.blocking:
        add(f"blocked by: {diagnosis.blocking}")
    else:
        add("blocked by: nothing — the next action's preconditions all hold")
    add("")
    add("next action:")
    for line in _wrap(diagnosis.next_action):
        add(f"  {line}")
    if diagnosis.next_stage:
        add("")
        add(f"stage to invoke: {diagnosis.next_stage}")
    if diagnosis.relay:
        add("")
        add("relay this verbatim (R-8.1 — never soften it, never summarise it):")
        add("-" * 78)
        add(diagnosis.relay)
        add("-" * 78)
    for note in diagnosis.notes:
        add("")
        add("note:")
        for line in _wrap(note):
            add(f"  {line}")
    if diagnosis.drift:
        add("")
        add("repository drift (R-8.3 — surfaced, never adjudicated):")
        for flag in diagnosis.drift:
            recorded = ", ".join(f"{k} {v}" for k, v in flag["recorded"].items())
            add(f"  between {flag['between']}: {recorded}")
            for line in _wrap(f"decided by {flag['decided_by']}"):
                add(f"    {line}")
    if diagnosis.open_run:
        add("")
        state = "open" if diagnosis.open_run.get("open") else "not open"
        add(f"open run (R-4.4): {state} — {diagnosis.open_run.get('why')}")
    add("")
    add(f"checks run: {len(diagnosis.checks)}")
    for check in diagnosis.checks:
        add(f"  {'ok  ' if check.ok else 'FAIL'} {check.name}")
    return "\n".join(lines) + "\n"


def _wrap(text, width=76):
    words, line, out = (text or "").split(), "", []
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out or [""]


# --------------------------------------------------------------------------------------
# R-10.2's checksums, and R-11's before-and-after comparison
# --------------------------------------------------------------------------------------


def checksums(repo, paths):
    """One hash per stage artifact, held nowhere.

    R-11 asks that a checksum of all stage artifacts before and after an orchestrator
    invocation differ only by what the invoked stages themselves wrote. This is how R-9.1 —
    never edit a stage artifact — becomes checkable rather than only asserted: take a set
    before invoking a stage, take one after, and every difference must be attributable to that
    stage. R-10.2 forbids storing the set, so this prints and returns.
    """
    out = {}
    for name, default in ARTIFACTS:
        relative = paths.get(name, default)
        full = os.path.join(repo, relative)
        if not os.path.isfile(full):
            out[relative] = None
            continue
        digest = hashlib.sha256()
        with open(full, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):  # noqa: B023
                digest.update(chunk)
        out[relative] = digest.hexdigest()
    return out


# --------------------------------------------------------------------------------------
# The self-test: every position in the table, driven from the fixtures
# --------------------------------------------------------------------------------------


def _fixtures_root(override=None):
    """Where the fixture files live. Searched rather than computed, and deliberately so.

    A skill can legitimately be installed in more than one place — directory-scoped under a
    projects tree, or globally under the user's home — and the two put a different number of
    directories between this file and the requirements repository. Computing the path from this
    file's location works from exactly one of them and fails confusingly from the other, which
    is what it did the first time this skill was installed globally.

    So the candidates are tried in order and the first one holding the fixtures wins.
    """
    if override:
        return override

    here = os.path.dirname(os.path.abspath(__file__))
    dot_claude = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    candidates = [
        # Directory-scoped install: <somewhere>/.claude/skills/... beside <somewhere>/repo
        os.path.join(os.path.dirname(dot_claude), "code-coverager", "fixtures"),
        # Global install under the home directory, with the repository under ~/Projects
        os.path.join(os.path.expanduser("~"), "Projects", "code-coverager", "fixtures"),
        # Run from the requirements repository itself
        os.path.join(os.getcwd(), "fixtures"),
    ]
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "synthetic-plan.md")):
            return candidate
    return candidates[0]


SELFTEST_CASES = (
    # (position, assessment fixture, plan fixture, ledger fixture, sheet, mutation)
    ("not-a-repository", None, None, None, None, "NO-GIT"),
    ("no-assessment", None, None, None, None, None),
    ("assessment-invalid", "unreconciled-assessment.md", None, "ledger.json", None, None),
    ("no-plan", "synthetic-assessment.md", None, None, None, None),
    ("plan-invalid", "synthetic-assessment.md", "broken-plan.md", None, None, None),
    ("awaiting-approval", "synthetic-assessment.md", "synthetic-plan.md", None, None, None),
    ("ready-to-execute", "synthetic-assessment.md", "reviewed-plan.md", None, None, None),
    # An interrupted run has no fixture file of its own and is synthesised here, by writing one
    # executor status onto the reviewed plan. That is deliberate rather than a shortcut: the
    # artifact it would stand for lints clean at no phase at all, which is the defining
    # property of an interrupted run and the reason stage three refuses to resume one. A file
    # like that sitting in `fixtures/` would be the one fixture whose expected lint result is
    # "broken at every phase, for no rule in particular", which teaches nothing about the
    # linter and would need a paragraph of the README explaining why it is not a mistake.
    ("execution-incomplete", "synthetic-assessment.md", "reviewed-plan.md", None, None,
     "INTERRUPT"),
    ("executed", "synthetic-assessment.md", "executed-plan.md", None, None, None),
    ("closeout-answered", "synthetic-assessment.md", "executed-plan.md", None, "SHEET", None),
    ("awaiting-closeout", "synthetic-assessment.md", "executed-plan.md", None,
     "SHEET-UNANSWERED", None),
    # `closed` is the one position with no fixture set, and it is validated against
    # `~/Projects/design-os` instead. Reaching it needs a report that passes `trace_report.py`,
    # which regenerates the report from the run record and demands every generated byte match —
    # so a hand-written fixture report would be a report nothing generated, wearing the
    # authority of one that was. The real closed run is the honest test and it already exists.
)


def selftest():
    """Drive every position in the table and assert the diagnosis and the next action.

    Two properties are asserted, and the second is R-4.3's:

    1. Each fixture set reaches the position it was built to stand for.
    2. A second derivation against the same unchanged inputs is byte-identical to the first.

    The second is not a formality. Three of the checks below are subprocesses whose output is
    captured into the diagnosis, and a check that reported a timestamp, a path that varied, or
    a set iterated in hash order would produce two different diagnoses from one repository —
    which is the failure R-4.3 exists to forbid, and the only way to see it is to look.
    """
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    fixtures = _fixtures_root()
    if not os.path.isdir(fixtures):
        print(f"cannot find the fixtures at {fixtures}", file=sys.stderr)
        return 2

    failures = []
    for expected, assessment, plan, ledger, sheet, mutation in SELFTEST_CASES:
        workspace = tempfile.mkdtemp(prefix="pipeline-selftest-")
        try:
            docs = os.path.join(workspace, "docs")
            os.makedirs(docs)
            for name, target in (
                (assessment, "test-assessment.md"), (plan, "test-plan.md"),
                (ledger, "test-ledger.json"),
            ):
                if name:
                    shutil.copy(os.path.join(fixtures, name), os.path.join(docs, target))
            if mutation == "INTERRUPT":
                _interrupt_run(os.path.join(docs, "test-plan.md"))
            if sheet:
                _write_selftest_sheet(workspace, docs, answered=sheet == "SHEET")
            with open(os.path.join(workspace, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("fixture workspace\n")
            if mutation != "NO-GIT":
                subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
                subprocess.run(["git", "config", "user.email", "t@example.com"],
                               cwd=workspace, check=True)
                subprocess.run(["git", "config", "user.name", "Fixture"], cwd=workspace,
                               check=True)
                subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
                subprocess.run(["git", "commit", "-qm", "fixtures"], cwd=workspace, check=True)

            first = derive(workspace)
            second = derive(workspace)
            if first.position != expected:
                failures.append(
                    f"{expected}: derived {first.position!r} instead"
                    + (f"\n      blocked by: {first.blocking}" if first.blocking else "")
                )
            elif not first.next_action:
                failures.append(f"{expected}: reached the position and proposed no action")
            else:
                print(f"ok   {expected:22s} -> {first.next_stage or 'stop'}")

            left = json.dumps(_comparable(first.as_dict(), workspace), sort_keys=True)
            right = json.dumps(_comparable(second.as_dict(), workspace), sort_keys=True)
            if left != right:
                failures.append(
                    f"{expected}: R-4.3 — two derivations against unchanged inputs disagree"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    print()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"all {len(SELFTEST_CASES)} positions derived correctly, and each derivation "
          "is idempotent (R-4.3)")
    return 0


def _comparable(payload, workspace):
    """The diagnosis with the temporary path removed, so two runs can be compared literally."""
    text = json.dumps(payload)
    return json.loads(text.replace(workspace, "<workspace>"))


def _interrupt_run(plan_path):
    """Leave the reviewed plan looking like a run that started and stopped.

    One item moves from `pending` to `done` and nothing else changes, which is exactly what an
    interrupted run leaves behind: a status only the executor writes, and no run summary
    because the summary is written at the end.
    """
    with open(plan_path, encoding="utf-8") as handle:
        text = handle.read()
    assert "status: pending\n" in text, plan_path
    with open(plan_path, "w", encoding="utf-8") as handle:
        handle.write(text.replace("status: pending\n", "status: done\n", 1))


def _write_selftest_sheet(workspace, docs, answered):
    """Compose the close-out sheet for the executed fixture, using stage four's own writer.

    Written by `closeout.render_brief` rather than by hand, for the same reason the state
    deriver reads it with `closeout.validate_answers`: the sheet's shape is stage four's, and a
    fixture sheet this skill composed itself would test the orchestrator against a format
    nothing else produces.
    """
    closeout = siblings.closeout()
    planio = siblings.planio()
    plan = planio.Plan(os.path.join(docs, "test-plan.md"), phase="executed", lint_writes=False)
    text = closeout.render_brief(plan, workspace)
    if answered:
        text = text.replace(
            "option:            # fix-the-code | requirement-wrong | accept-with-red | downgrade",
            "option: accept-with-red",
        ).replace(
            "decided-by:        # your name; a decision with no decider is not a decision",
            "decided-by: The Owner",
        ).replace(
            'date:              # "YYYY-MM-DD", quoted',
            'date: "2026-08-04"',
        ).replace(
            "rationale: >\n"
            "  # Why this answer rather than the other three. The next run re-reports an open\n"
            "  # defect and the reader needs to know what was already weighed.",
            "rationale: >\n"
            "  The failure is real and the fix belongs to whoever owns this module, so the\n"
            "  test stays red as the ready-made verification for that work.",
        )
    with open(os.path.join(docs, "test-closeout.md"), "w", encoding="utf-8") as handle:
        handle.write(text)


# --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Where the run stands, derived from the artifacts and nothing else (R-4.1)."
    )
    parser.add_argument("--repo", default=".", help="the repository root")
    parser.add_argument("--assessment", default=DEFAULT_ASSESSMENT)
    parser.add_argument("--plan", default=DEFAULT_PLAN)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--sheet", default=DEFAULT_SHEET)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true", help="emit the diagnosis as data")
    parser.add_argument("--checksums", action="store_true",
                        help="print one hash per stage artifact and exit (R-10.2, R-11)")
    parser.add_argument("--selftest", action="store_true",
                        help="drive every position from the fixtures and check R-4.3")
    arguments = parser.parse_args()

    if arguments.selftest:
        return selftest()

    repo = os.path.abspath(arguments.repo)
    paths = {
        "assessment": arguments.assessment, "plan": arguments.plan,
        "ledger": arguments.ledger, "closeout_sheet": arguments.sheet,
        "report": arguments.report,
    }

    if arguments.checksums:
        digests = checksums(repo, paths)
        if arguments.json:
            print(json.dumps(digests, indent=2))
        else:
            for path, digest in digests.items():
                print(f"{digest or '-' * 64}  {path}")
        return 0

    diagnosis = derive(repo, arguments.assessment, arguments.plan, arguments.ledger,
                       arguments.sheet, arguments.report)
    if arguments.json:
        print(json.dumps(diagnosis.as_dict(), indent=2))
    else:
        sys.stdout.write(render(diagnosis))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Resolve the four sibling skills this one conducts, and fail by name when one is absent.

Stage five carries no analytical tooling of its own. Every check it performs is a check one of
the four stages already owns, and this module is how it reaches them:

* ``test-assessment/scripts/check_index.py`` — whether an assessment report's machine-readable
  index is valid, which is the whole of the entry precondition into planning.
* ``test-planning/scripts/read_assessment.py`` — the planner's own hard stop, so that an
  unindexed report produces the message the planner would have produced.
* ``test-planning/scripts/plan_lint.py`` — the plan's validity at each of its four phases,
  which is how three separate pipeline positions are told apart.
* ``test-execution/scripts/preflight.py`` — the execution gate, which the orchestrator invokes
  in ``--dry-run`` form to read a verdict and never to establish one.
* ``test-reporting/scripts/closeout.py``, ``run_record.py``, ``ledger.py`` and
  ``reconcile.py`` — the close-out sheet, the run record's cross-checks, the run ledger's
  open-items query, and the reconciliation comparison.

**This module bootstraps off stage four's ``siblings.py``, which bootstraps off stage
three's.** Stage three's file is the single place the side-by-side install assumption lives.
Stage four added the accessors stage three did not need; this one adds the accessors neither
needed, because neither of them had reason to run the assessment's index checker or the
planner's hard stop. Restating the assumption here would make a third place to update when it
changes, and the suite has been bitten twice by two copies of one statement drifting.

What is new here rather than inherited: every module this stage reaches for is reached as a
*subprocess* as well as an import. The state deriver runs these scripts by their command line
so it can capture the exact text a failing one prints, because R-8.1 requires a stage's
diagnosis to be relayed verbatim and a re-worded exception is not verbatim. The accessors below
therefore return the module for the callers that want its constants, and ``path_of`` returns
the file for the callers that want to run it.

Usage:
    python3 siblings.py        # report what is present, without running anything
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS = os.path.dirname(os.path.dirname(_HERE))

ASSESSMENT = os.path.join(_SKILLS, "test-assessment", "scripts")
PLANNING = os.path.join(_SKILLS, "test-planning", "scripts")
EXECUTION = os.path.join(_SKILLS, "test-execution", "scripts")
REPORTING = os.path.join(_SKILLS, "test-reporting", "scripts")

_DIRECTORY_OF = {
    "test-assessment": ASSESSMENT,
    "test-planning": PLANNING,
    "test-execution": EXECUTION,
    "test-reporting": REPORTING,
}


class MissingSibling(Exception):
    """A sibling skill this stage needs is not installed beside it."""

    def __init__(self, skill, module, purpose):
        self.skill = skill
        self.module = module
        self.purpose = purpose
        super().__init__(self.instruction())

    def instruction(self):
        return f"""\
STOP: the `{self.skill}` skill is not installed beside this one.

Stage five needs {self.skill}/scripts/{self.module}, {self.purpose}

It looked in:
    {os.path.join(_SKILLS, self.skill, 'scripts')}

The five skills of this suite — test-assessment, test-planning, test-execution,
test-reporting, test-pipeline — are installed as siblings in one skills directory, and each
later stage reaches the earlier ones rather than carrying copies that would drift.

This stage depends on that arrangement more completely than any other, because it has no
analytical tooling of its own: it is the skill that conducts the other four, so a missing
sibling is not a degraded capability but an absent one. There is nothing here to fall back
on and nothing to reimplement — a second index checker or a second plan linter would be a
second opinion about whether a stage may advance, which is the one question this skill
exists to answer consistently.

To fix it, install `{self.skill}` alongside this skill, or copy it into the same directory.
Then run this again.
"""


def _require(skill, module, purpose):
    """Confirm the file exists and put its directory on the import path. Returns the path."""
    directory = _DIRECTORY_OF[skill]
    path = os.path.join(directory, module)
    if not os.path.isfile(path):
        raise MissingSibling(skill, module, purpose)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return path


_REPORTING_SIBLINGS = None


def _reporting_siblings():
    """Stage four's resolver, which bootstraps off stage three's, which owns the assumption.

    Loaded by path under a name of its own rather than with a plain ``import siblings``. Three
    files in this suite are called ``siblings.py``, so a plain import finds whichever is already
    in ``sys.modules`` — which, when this module is imported rather than run directly, is this
    one, and the delegation below becomes infinite recursion. Stage four's copy of this comment
    records that it did exactly that the first time it was run from another script, and the
    traceback was a thousand identical frames with the real problem nowhere in it.
    """
    global _REPORTING_SIBLINGS  # noqa: PLW0603
    if _REPORTING_SIBLINGS is not None:
        return _REPORTING_SIBLINGS

    import importlib.util  # noqa: PLC0415

    path = _require(
        "test-reporting",
        "siblings.py",
        "which is where stage four resolves its own siblings, and which in turn bootstraps "
        "off stage three's — the single place the side-by-side install assumption lives. "
        "Stage five bootstraps off stage four rather than restating it.",
    )
    spec = importlib.util.spec_from_file_location("test_reporting_siblings", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_reporting_siblings"] = module
    spec.loader.exec_module(module)
    _REPORTING_SIBLINGS = module
    return module


# --------------------------------------------------------------------------------------
# Inherited accessors. Nothing new is asserted here; the chain resolves them.
# --------------------------------------------------------------------------------------


def planlib():
    """The plan parser and schemas. Gate brief extraction reads blocks through it."""
    return _reporting_siblings().planlib()


def plan_lint():
    """The plan linter, whose four phases distinguish three pipeline positions."""
    return _reporting_siblings().plan_lint()


def planio():
    """The plan reader-and-writer. Stage five uses only its reading half, deliberately.

    ``planio.Plan`` indexes every block kind in the plan, including stage four's, which makes
    it the cheapest correct way to ask how many defects a run registered or whether a target
    was approved. Its writing half is never called from this skill and never may be: R-9.1
    forbids the orchestrator from editing a stage artifact, and this is the module that could.
    """
    _require(
        "test-execution",
        "planio.py",
        "which indexes every block in a plan, including stage four's. Stage five reads plans "
        "through it and never writes through it: R-9.1 forbids the orchestrator from editing "
        "a stage artifact, and this is the module that could.",
    )
    import planio as module  # noqa: PLC0415

    return module


# --------------------------------------------------------------------------------------
# What stage five adds: the four validators no earlier stage had reason to run.
# --------------------------------------------------------------------------------------


def check_index():
    """The assessment's own index checker, which decides `assessment-invalid`."""
    _require(
        "test-assessment",
        "check_index.py",
        "which validates an assessment report's machine-readable index. Whether that index is "
        "valid is the whole of the entry precondition into planning (R-6.2), and this is the "
        "only thing in the suite that decides it.",
    )
    import check_index as module  # noqa: PLC0415

    return module


def read_assessment():
    """The planner's hard stop, so the orchestrator relays the planner's own words."""
    _require(
        "test-planning",
        "read_assessment.py",
        "which is the planning stage's hard stop on an unindexed or under-versioned "
        "assessment. R-6.2 says the orchestrator surfaces that stop verbatim rather than "
        "working around it, which means running the thing that produces it.",
    )
    import read_assessment as module  # noqa: PLC0415

    return module


def preflight():
    """Stage three's gate. Invoked with --dry-run to read a verdict, never to establish one."""
    _require(
        "test-execution",
        "preflight.py",
        "which is the execution gate and, under the amended R-6.4, the final arbiter of "
        "everything between plan approval and the first work item. The orchestrator invokes "
        "it rather than anticipating it.",
    )
    import preflight as module  # noqa: PLC0415

    return module


def closeout():
    """The close-out gate: the sheet stage four writes and the answers it reads back."""
    _require(
        "test-reporting",
        "closeout.py",
        "which writes the close-out decision sheet and reads the owner's answers back. Gate "
        "two's brief is composed from that sheet, and whether the sheet is answered is what "
        "tells `awaiting-closeout` from `closeout-answered`.",
    )
    import closeout as module  # noqa: PLC0415

    return module


def run_record():
    """Stage four's input verification, which R-6.5 makes the reporting precondition."""
    _require(
        "test-reporting",
        "run_record.py",
        "which performs R-4.2's cross-checks of the run against the plan. R-6.5 makes the run "
        "summary's consistency under stage four's own input verification the precondition for "
        "reporting, and this is that verification.",
    )
    import run_record as module  # noqa: PLC0415

    return module


def ledger():
    """The run ledger: whether a run is named by one, and what it still holds open."""
    _require(
        "test-reporting",
        "ledger.py",
        "which is the only thing that reads or writes the run ledger. R-4.4's open-run "
        "derivation asks it whether any entry names this plan, and the closed position asks "
        "it whether the run was appended.",
    )
    import ledger as module  # noqa: PLC0415

    return module


def reconcile():
    """R-7.2's comparison of an assessment against the ledger's open items."""
    _require(
        "test-reporting",
        "reconcile.py",
        "which checks that an assessment confirms, updates, or contests every open ledger "
        "item. On a repository with a ledger this is part of whether an assessment is valid "
        "at all, so the orchestrator reads its verdict rather than forming one.",
    )
    import reconcile as module  # noqa: PLC0415

    return module


def path_of(skill, module):
    """The file path of a sibling script, for the callers that run it as a subprocess.

    The state deriver runs these scripts by their command line rather than calling into them,
    and the reason is R-8.1: a stage's diagnosis is relayed verbatim, and a diagnosis
    reconstructed from a caught exception is not verbatim. It is the same text re-worded by the
    orchestrator, which is exactly what that requirement forbids.
    """
    return _require(
        skill,
        module,
        "which the state deriver runs as a subprocess so that a failure's own words reach the "
        "owner unedited (R-8.1).",
    )


def main():
    """Report what is present, so a broken install can be diagnosed without a run."""
    ok = True
    for name, loader in (
        ("test-assessment/check_index.py", check_index),
        ("test-planning/read_assessment.py", read_assessment),
        ("test-planning/planlib.py", planlib),
        ("test-planning/plan_lint.py", plan_lint),
        ("test-execution/planio.py", planio),
        ("test-execution/preflight.py", preflight),
        ("test-reporting/closeout.py", closeout),
        ("test-reporting/run_record.py", run_record),
        ("test-reporting/ledger.py", ledger),
        ("test-reporting/reconcile.py", reconcile),
    ):
        try:
            loader()
            print(f"ok: {name}")
        except MissingSibling as error:
            ok = False
            print(f"MISSING: {name}\n\n{error.instruction()}", file=sys.stderr)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

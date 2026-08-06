#!/usr/bin/env python3
"""Resolve the sibling skills this stage depends on, and fail by name when they are absent.

Stage four carries no copy of the plan parser, the plan linter, the plan writer, the check
runner, the suite reader, the footprint measurer, or the coverage parser. It imports every one
of them from the skill that owns it.

**This module bootstraps off stage three's ``siblings.py`` rather than duplicating it.** That
file is the single place the side-by-side install assumption lives, and the assumption is
identical here — so a second copy of it would be a second place to update when the assumption
changes, which is exactly the drift this whole arrangement exists to prevent. What this module
adds is the accessors stage three did not need to expose: ``planio`` (the writer), ``suite``
(the runner output reader), ``check_runner`` (the eight check kinds and the mutation protocol),
and ``actuals`` (footprint measurement from a commit diff).

The failure mode is the one worth engineering for: an ImportError three frames into a
close-out, with a half-applied decision on the branch. Every accessor here checks the file
exists first and raises a stop that names the missing skill, what stage four wanted it for, and
where it looked.

Usage:
    python3 siblings.py        # report what is present, without running anything
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS = os.path.dirname(os.path.dirname(_HERE))

PLANNING = os.path.join(_SKILLS, "test-planning", "scripts")
ASSESSMENT = os.path.join(_SKILLS, "test-assessment", "scripts")
EXECUTION = os.path.join(_SKILLS, "test-execution", "scripts")


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

Stage four needs {self.skill}/scripts/{self.module}, {self.purpose}

It looked in:
    {os.path.join(_SKILLS, self.skill, 'scripts')}

The four skills of this suite — test-assessment, test-planning, test-execution,
test-reporting — are installed as siblings in one skills directory, and each later stage
imports from the earlier ones rather than carrying its own copies. Two copies of the plan
schema, or of the check runner, would be two opinions that drift apart the first time either
is edited.

To fix it, install `{self.skill}` alongside this skill, or copy it into the same directory.
Then run this again. Do not work around it by reimplementing what is missing: for this stage
in particular, a second check runner that disagrees with the first would verify a close-out
consequence against rules nobody else uses.
"""


def _require(directory, skill, module, purpose):
    path = os.path.join(directory, module)
    if not os.path.isfile(path):
        raise MissingSibling(skill, module, purpose)
    if directory not in sys.path:
        sys.path.insert(0, directory)


_EXECUTION_SIBLINGS = None


def _execution_siblings():
    """Stage three's own resolver, which is where the install assumption is defined.

    Loaded by path under a name of its own rather than with a plain ``import siblings``. Both
    files are called ``siblings.py``, so a plain import finds whichever is already in
    ``sys.modules`` — which, when this module is imported rather than run directly, is this
    one, and the delegation below becomes infinite recursion. It did exactly that the first
    time this was run from another script, and the traceback was a thousand identical frames
    with the real problem nowhere in it.
    """
    global _EXECUTION_SIBLINGS  # noqa: PLW0603
    if _EXECUTION_SIBLINGS is not None:
        return _EXECUTION_SIBLINGS

    import importlib.util  # noqa: PLC0415

    _require(
        EXECUTION,
        "test-execution",
        "siblings.py",
        "which is the single place the side-by-side install assumption lives. Stage four "
        "bootstraps off it rather than restating it.",
    )
    path = os.path.join(EXECUTION, "siblings.py")
    spec = importlib.util.spec_from_file_location("test_execution_siblings", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_execution_siblings"] = module
    spec.loader.exec_module(module)
    _EXECUTION_SIBLINGS = module
    return module


def planlib():
    """The plan parser, schemas, and validator — including stage four's own block shapes."""
    return _execution_siblings().planlib()


def plan_lint():
    """The plan linter, which is this stage's gate exactly as it was stage three's."""
    return _execution_siblings().plan_lint()


def parse_coverage():
    """The assessment stage's five-format coverage report parser."""
    return _execution_siblings().parse_coverage()


def planio():
    """The plan writer: span-exact in-place rewrites, re-linted and rolled back on failure.

    Stage four writes four new block kinds into the plan, and it writes them through the same
    writer stage three uses, for the same reason: the plan being written into is the plan the
    owner reviewed and commented on, and a round trip through a YAML emitter would return a
    technically equivalent file with every comment gone.
    """
    _require(
        EXECUTION,
        "test-execution",
        "planio.py",
        "which is the only writer that edits a plan in place without destroying the owner's "
        "review comments, and which re-lints and rolls back every write.",
    )
    import planio as module  # noqa: PLC0415

    return module


def check_runner():
    """The eight check kinds and the mutation protocol.

    R-6.2 verifies each close-out consequence through the check runner before the gate
    advances. Verifying it any other way would mean stage four had its own opinion about what
    a passing check is, which is how two verification standards start.
    """
    _require(
        EXECUTION,
        "test-execution",
        "check_runner.py",
        "which verifies every close-out consequence (R-6.2) using the same eight check kinds "
        "and the same mutation protocol the execution stage ran.",
    )
    import check_runner as module  # noqa: PLC0415

    return module


def suite():
    """Running a command and reading which tests failed out of its output."""
    _require(
        EXECUTION,
        "test-execution",
        "suite.py",
        "which runs the suite and reads failures out of reporter output. The final suite "
        "state in the run record is measured with it.",
    )
    import suite as module  # noqa: PLC0415

    return module


def actuals():
    """Footprint measurement from a commit diff, never from self-report.

    R-6.3 confines the close-out executor's edit surface to the named test and claim of the
    decision being applied. Measuring that surface from the commit rather than from what the
    executor believes it touched is the difference between a rule and a hope.
    """
    _require(
        EXECUTION,
        "test-execution",
        "actuals.py",
        "which measures what a commit actually touched, so R-6.3's edit surface is checked "
        "against the repository rather than against the executor's own account of itself.",
    )
    import actuals as module  # noqa: PLC0415

    return module


def main():
    """Report what is present, so a broken install can be diagnosed without a run."""
    ok = True
    for name, loader in (
        ("test-execution/planio.py", planio),
        ("test-execution/check_runner.py", check_runner),
        ("test-execution/suite.py", suite),
        ("test-execution/actuals.py", actuals),
        ("test-planning/planlib.py", planlib),
        ("test-planning/plan_lint.py", plan_lint),
        ("test-assessment/parse_coverage.py", parse_coverage),
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

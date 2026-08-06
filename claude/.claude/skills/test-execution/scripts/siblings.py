#!/usr/bin/env python3
"""Resolve the two sibling skills this one depends on, and fail by name when they are absent.

Stage three does not carry its own copy of the plan parser or the coverage parser. It imports
them from the skills that own them:

* ``test-planning/scripts/planlib.py`` and ``plan_lint.py`` — the plan's schema and its gate.
  Execution R-4.2 makes the stage two linter this stage's entry gate, so a second copy would
  be a second opinion about what a legal plan is, and the two would drift apart the first time
  either was edited.
* ``test-assessment/scripts/parse_coverage.py`` — every ``coverage-delta`` entry is checked
  against real coverage output, in whichever of five formats the repository produces. That
  parser is fifteen kilobytes of format handling and this project has already been bitten
  twice by two copies of one statement drifting.

**The cost is an assumption: the three skills are installed side by side.** They are, at
``~/Projects/.claude/skills/``, and the parent-directory discovery that puts them there is
what makes them available from any repository under that tree. But the assumption is real
interface debt, and this module exists so that when it breaks the failure names the problem
and the fix rather than surfacing as an ImportError three frames deep.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS = os.path.dirname(os.path.dirname(_HERE))

PLANNING = os.path.join(_SKILLS, "test-planning", "scripts")
ASSESSMENT = os.path.join(_SKILLS, "test-assessment", "scripts")


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

This stage needs {self.skill}/scripts/{self.module}, {self.purpose}

It looked in:
    {os.path.join(_SKILLS, self.skill, 'scripts')}

The three skills of this suite — test-assessment, test-planning, test-execution — are
installed as siblings in one skills directory, and this stage imports from the other two
rather than carrying its own copies. Two copies of the plan schema, or of the coverage
parser, would be two opinions that drift apart the first time either is edited.

To fix it, install `{self.skill}` alongside this skill, or copy it into the same
directory. Then run this again. Do not work around it by reimplementing what is missing:
a second parser that disagrees with the first is worse than a stop.
"""


def _require(directory, skill, module, purpose):
    path = os.path.join(directory, module)
    if not os.path.isfile(path):
        raise MissingSibling(skill, module, purpose)
    if directory not in sys.path:
        sys.path.insert(0, directory)


def planlib():
    """The plan parser, schemas, and validator."""
    _require(
        PLANNING,
        "test-planning",
        "planlib.py",
        "which defines the plan's YAML subset, its schemas, and the line spans this stage "
        "writes back through.",
    )
    import planlib as module  # noqa: PLC0415

    return module


def plan_lint():
    """The stage two linter, which is this stage's entry gate (R-4.2)."""
    _require(
        PLANNING,
        "test-planning",
        "plan_lint.py",
        "which is this stage's entry gate: R-4.2 requires the plan to pass the stage two "
        "linter before execution begins, and every write this stage makes is re-linted.",
    )
    import plan_lint as module  # noqa: PLC0415

    return module


def parse_coverage():
    """The assessment stage's coverage report parser."""
    _require(
        ASSESSMENT,
        "test-assessment",
        "parse_coverage.py",
        "which reads LCOV, Cobertura, coverage.py JSON, Istanbul, and Go profile output. "
        "Every `coverage-delta` entry in the plan is checked against it.",
    )
    import parse_coverage as module  # noqa: PLC0415

    return module


def main():
    """Report what is present, so a broken install can be diagnosed without a run."""
    ok = True
    for name, loader in (
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

#!/usr/bin/env python3
"""The gate stage three does not start without. R-4.1 to R-4.5, deterministically.

Six things happen here, and the order matters because each one assumes the last:

1. **The plan is approved** (R-4.1). `plan-meta.approved`, not `target.approved` — the second
   approves a coverage number and the first approves a plan.
2. **The plan lints clean at `--phase reviewed`**, with the assessment, so the completeness
   and claim-enablement rules run (R-4.2).
3. **Every resolved decision's rewrite has been applied** (R-4.2). An owner who answers a
   question whose answer rewrites three items has not finished until those three items say
   what the answer implies. Nothing else checks this, and an unapplied rewrite means the
   executor builds the wrong thing while every check passes.
4. **Every unresolved decision's blocked items are marked `skipped`** (R-4.2). This one is a
   write rather than a check.
5. **Commit drift is measured, and stale targets are marked** (R-4.3). Drift never silently
   invalidates the run and never silently proceeds.
6. **The suite runs once and its failures are recorded** (R-4.4), then the work branch is
   created (R-4.5).

**Every failure prints what to do.** The shape is `read_assessment.py`'s: a stop, then the
instruction, because a gate that says only "no" costs a round trip to find out why.

Usage:
    python3 preflight.py docs/test-plan.md --assessment docs/test-assessment.md --repo .
    python3 preflight.py docs/test-plan.md --assessment docs/test-assessment.md --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planio  # noqa: E402
import siblings  # noqa: E402
import suite  # noqa: E402

planlib = siblings.planlib()
plan_lint = siblings.plan_lint()

DEFAULT_LOG_DIR = "docs/test-execution-log"


class Stop(Exception):
    """Pre-flight failed in a way that must not be worked around."""

    def __init__(self, message, instruction):
        self.message = message
        self.instruction = instruction
        super().__init__(message)


# --------------------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------------------


def git(repo, *arguments, check=False):
    completed = subprocess.run(
        ["git", *arguments], cwd=repo, capture_output=True, text=True
    )
    if check and completed.returncode != 0:
        raise Stop(
            f"`git {' '.join(arguments)}` failed: {completed.stderr.strip()}",
            "Pre-flight needs a working git repository: it measures commit drift, creates "
            "the work branch, and reads every item's actual footprint from a commit diff. "
            "Run this from inside the repository the plan targets.",
        )
    return completed


def head_commit(repo):
    completed = git(repo, "rev-parse", "HEAD")
    return completed.stdout.strip() if completed.returncode == 0 else None


def working_tree_state(repo, ignore):
    """Paths with uncommitted changes, excluding the ones pre-flight expects to be dirty."""
    completed = git(repo, "status", "--porcelain")
    dirty = []
    for line in completed.stdout.split("\n"):
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ")[-1]
        if any(path == entry or path.startswith(entry.rstrip("/") + "/") for entry in ignore):
            continue
        dirty.append(path)
    return dirty


# --------------------------------------------------------------------------------------
# R-4.1 and R-4.2
# --------------------------------------------------------------------------------------


def check_approved(plan):
    if plan.meta is None:
        raise Stop(
            f"{plan.path} has no `plan-meta` block",
            "This does not look like a plan produced by the test-planning skill. Check the "
            "path.",
        )
    approved = plan.meta.node.get("approved")
    if isinstance(approved, dict) and approved.get("by"):
        return {"by": approved.get("by"), "date": approved.get("date"),
                "note": approved.get("note")}
    raise Stop(
        f"{plan.path} carries no plan approval",
        """\
R-4.1: an unapproved plan is never executed.

Approval is the owner's act at the review sitting, and it is not the same act as approving
the coverage target. `target.approved` approves a number; this approves the plan, and the
sitting also resolves escalations and ratifies claims. An owner may perfectly well approve
the plan while deferring the number.

Add to the `plan-meta` block, once the owner has actually reviewed it:

    approved:
      by: "<who>"
      date: "<when>"
      note: >
        <anything worth recording about what was and was not approved>

`references/review-brief.md` in the test-planning skill is what the review sitting involves.
Do not add this field on the owner's behalf.""",
    )


def check_not_already_executed(plan_path):
    """Stop on a plan that has already been written into, rather than failing obscurely.

    Resumption after an interrupted run is deferred — it is an open question in the execution
    requirements, and the one-commit-per-item rule exists to keep it tractable whenever it is
    answered. What must not happen meanwhile is this: R-4.2 lints at `--phase reviewed`, an
    already-executed plan carries statuses and fields that phase forbids, and the run stops
    with twenty `premature-status` failures that describe the symptom and not the situation.

    Detected from the plan text rather than the parsed plan, because this runs before the
    plan is loaded and a half-written plan may not parse at all.
    """
    problems = []
    with open(plan_path, encoding="utf-8") as handle:
        text = handle.read()

    for kind in sorted(planlib.EXECUTION_BLOCKS):
        if f"```yaml {kind}" in text:
            problems.append(f"a `{kind}` block")
    for field in ("actuals:", "diagnosis:", "commit:"):
        if re.search(r"^" + re.escape(field), text, re.MULTILINE):
            problems.append(f"an item-level `{field.rstrip(':')}` field")
    for status in sorted(planlib.STATUSES - plan_lint.PRE_REVIEW_STATUSES):
        if re.search(r"^status:\s*" + re.escape(status) + r"\s*$", text, re.MULTILINE):
            problems.append(f"an item with status `{status}`")

    if not problems:
        return
    raise Stop(
        f"{plan_path} has already been executed against",
        f"""\
The plan carries writeback from a previous run: {', '.join(sorted(set(problems)))}.

**Resuming an interrupted run is not implemented.** It is an open question in this stage's
requirements, deliberately deferred: re-entering at the first non-terminal item on the
existing branch and starting a fresh branch are different answers with different failure
modes, and choosing between them needs real runs behind it. The one-commit-per-item rule
exists so that whichever is chosen later is tractable.

So there are two supported ways forward, and they are different decisions:

  * **Start over from the plan as the owner approved it.** Restore the plan file from the
    commit it was approved at and delete the work branch:

        git checkout <the approving commit> -- {plan_path}
        git switch <your base branch>
        git branch -D <the work branch>

    Anything the previous run committed on that branch is lost.

  * **Keep the previous run's results.** Do not run pre-flight again. The plan is the
    running record and it already holds what happened; take it to stage four as it stands,
    partial and honest, and re-plan the items that did not complete.

Pre-flight will not choose between those for you, because one of them destroys work. If you
only want to see what pre-flight would say, pass --dry-run, which writes nothing.""",
    )


def check_lint(plan_path, assessment, phase="reviewed"):
    problems, _ = plan_lint.lint(plan_path, assessment, phase)
    if not problems:
        return
    problems.sort(key=lambda p: (p.line, p.rule))
    listing = "\n".join(f"  {problem}" for problem in problems)
    raise Stop(
        f"{plan_path} does not pass the stage two linter at --phase {phase} "
        f"({len(problems)} problem(s))",
        f"""\
R-4.2: the plan must pass the stage two linter, including the claim-enablement rule, before
anything executes. Every problem below names a file and a line.

{listing}

Fix them in the plan and run pre-flight again. Do not start the run around them: this linter
is also what every writeback is checked against during the run, so a plan that fails it now
is a plan stage three cannot record its own results into.""",
    )


# Which option a resolution chose. The resolution is free text written by the owner, and the
# convention that it names the option identifier is what makes it machine-readable at all.
def chosen_option(blocker_node):
    resolution = blocker_node.get("resolution")
    if not isinstance(resolution, str) or not resolution.strip():
        return None, None
    for option in blocker_node.get("options") or []:
        if not isinstance(option, dict):
            continue
        option_id = option.get("id")
        if isinstance(option_id, str) and re.search(
            r"(?<![\w-])" + re.escape(option_id) + r"(?![\w-])", resolution
        ):
            return option_id, option
    return None, resolution


def check_rewrites_applied(plan):
    """R-4.2: a resolved decision's option rewrite has actually been applied to the plan.

    This is the check with nothing else standing behind it. An owner answers a question whose
    answer drops two items and repoints a third; if the plan is not edited to match, every
    item still lints, every check still passes, and the executor builds the wrong thing
    faithfully. The `effect` field exists precisely so that this is checkable, and checking
    it is the only thing that makes writing it worthwhile.
    """
    problems = []
    for blocker_id, block in sorted(plan.blockers.items()):
        node = block.node
        option_id, option = chosen_option(node)
        if option_id is None:
            if isinstance(option, str):
                problems.append(
                    f"{blocker_id} carries a resolution that names none of its option "
                    f"identifiers ({', '.join(str(o.get('id')) for o in node.get('options') or [])}). "
                    "Nobody can tell which answer was chosen, including this check."
                )
            continue

        for effect in option.get("effect") or []:
            if not isinstance(effect, dict):
                continue
            item_id = effect.get("item")
            item = plan.items.get(item_id)

            if effect.get("drop") is True:
                if item is not None:
                    problems.append(
                        f"{blocker_id} was answered {option_id}, which drops {item_id}, and "
                        f"{item_id} is still in the plan."
                    )
                continue

            if item is None:
                problems.append(
                    f"{blocker_id} was answered {option_id}, which rewrites {item_id}, and "
                    f"no work item {item_id} exists to rewrite."
                )
                continue

            for key, expected in (effect.get("set") or {}).items():
                actual = planlib.to_plain(item.node.get(key))
                if actual != planlib.to_plain(expected):
                    problems.append(
                        f"{blocker_id} was answered {option_id}, which sets `{key}` on "
                        f"{item_id} to {planlib.to_plain(expected)!r}; it is {actual!r}."
                    )
            for key in effect.get("unset") or []:
                if key in item.node:
                    problems.append(
                        f"{blocker_id} was answered {option_id}, which unsets `{key}` on "
                        f"{item_id}; the field is still there."
                    )
            for claim_id in effect.get("remove-claims") or []:
                if claim_id in (item.node.get("claims") or []) or claim_id in (
                    item.node.get("claims-enabled") or []
                ):
                    problems.append(
                        f"{blocker_id} was answered {option_id}, which removes {claim_id} "
                        f"from {item_id}; the claim is still asserted."
                    )
            for claim_id in effect.get("add-claims") or []:
                if claim_id not in (item.node.get("claims") or []) and claim_id not in (
                    item.node.get("claims-enabled") or []
                ):
                    problems.append(
                        f"{blocker_id} was answered {option_id}, which adds {claim_id} to "
                        f"{item_id}; the claim is not there."
                    )
            for kind in effect.get("remove-checks") or []:
                if any(
                    isinstance(check, dict) and check.get("kind") == kind
                    for check in (item.node.get("completion-checks") or [])
                ):
                    problems.append(
                        f"{blocker_id} was answered {option_id}, which removes the `{kind}` "
                        f"check from {item_id}; the check is still there."
                    )

    if problems:
        listing = "\n".join(f"  - {problem}" for problem in problems)
        raise Stop(
            f"{len(problems)} resolved decision rewrite(s) have not been applied to the plan",
            f"""\
R-4.2: every resolved decision's option rewrite must be applied before execution begins.

{listing}

Apply each rewrite to the plan by hand, re-run the stage two linter, and run pre-flight
again. Stage three will not apply them for you: an option's `effect` says what a *plan*
becomes under an answer, and rewriting the plan is stage two's work. R-2.1 lists the plan
fields this stage may write, and none of them is one of these.

This is the one pre-flight check with nothing else standing behind it. If the rewrite is not
applied, every item still lints and every check still passes, and the run builds the wrong
thing faithfully.""",
        )


def mark_skipped(plan, dry_run):
    """R-4.2: the blocked items of an unresolved decision are skipped, not attempted.

    They keep their `blocked-by`. The blocker is the entire reason they were not attempted,
    and a run summary that says work was skipped without saying what would have unblocked it
    is not a report.
    """
    skipped = {}
    for blocker_id, block in sorted(plan.blockers.items()):
        if block.node.get("resolution"):
            continue
        for item_id in block.node.get("blocks") or []:
            if item_id in plan.items:
                skipped.setdefault(item_id, []).append(blocker_id)

    written = []
    for item_id in sorted(skipped, key=plan._item_key):
        current = plan.items[item_id].node.get("status")
        if current == "skipped":
            continue
        if current not in ("pending", "blocked-on-decision"):
            continue  # already terminal from an earlier run; leave it alone
        if not dry_run:
            plan.set_field("work-item", item_id, "status", "skipped")
        written.append(item_id)
    return skipped, written


# --------------------------------------------------------------------------------------
# R-4.3 — commit drift
# --------------------------------------------------------------------------------------

# How a function definition looks in the languages this suite supports. Cheap on purpose:
# R-4.3 asks pre-flight to revalidate targets *cheaply*, not to re-run the assessment's
# parser over the repository. A name that appears in a definition position is enough to say
# the target is still where the plan says it is.
_DEFINITION_PATTERNS = (
    r"^\s*(?:async\s+)?def\s+{name}\b",
    r"^\s*class\s+{name}\b",
    r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*{name}\b",
    r"^\s*(?:export\s+)?(?:const|let|var)\s+{name}\s*[:=]",
    r"^\s*(?:public|private|protected|static|\s)*{name}\s*\(",
    r"^\s*{name}\s*[:=]\s*(?:async\s*)?(?:function|\()",
    r"^\s*func\s+(?:\([^)]*\)\s*)?{name}\b",
)


# An item's target is often a file or a function the item is meant to *create*, which does not
# exist before the item runs. TARGET_SCHEMA carries no field marking a target that way — the
# only signal is English prose in `note` — so the tree at the planning commit is the authority
# instead: absent there and absent here means nothing moved, and absence is not drift.
_ABSENT = object()


def _at_commit(repo, commit, path):
    """The file's text at `commit`, `_ABSENT` if it was not in that tree, or None if git cannot
    say — no commit recorded, or one this repository does not have. None is the conservative
    answer, and callers keep their pre-drift behaviour rather than excusing the target."""
    if not commit:
        return None
    if git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}").returncode != 0:
        return None
    completed = git(repo, "show", f"{commit}:{path}")
    return completed.stdout if completed.returncode == 0 else _ABSENT


def _defines(text, name):
    return any(
        re.search(pattern.format(name=re.escape(name)), text, re.MULTILINE)
        for pattern in _DEFINITION_PATTERNS
    )


def target_still_there(repo, target, planned_commit=None):
    """Whether one `target` entry still resolves. Returns (ok, detail)."""
    path = target.get("file")
    if not isinstance(path, str):
        return True, None
    full = os.path.join(repo, path)
    if not os.path.exists(full):
        if _at_commit(repo, planned_commit, path) is _ABSENT:
            return True, None
        return False, f"{path} no longer exists"

    functions = [f for f in (target.get("functions") or []) if isinstance(f, str)]
    if not functions:
        return True, None

    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as error:
        return False, f"{path} could not be read: {error}"

    missing = [name for name in functions if not _defines(text, name)]
    if missing:
        prior = _at_commit(repo, planned_commit, path)
        if prior is not None:
            missing = [
                name
                for name in missing
                if _defines("" if prior is _ABSENT else prior, name)
            ]
    if missing:
        return False, (
            f"{path} no longer defines " + ", ".join(sorted(missing))
        )

    lines = target.get("lines")
    if isinstance(lines, str):
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", lines.strip())
        if match:
            last = int(match.group(2) or match.group(1))
            if last > text.count("\n") + 1:
                return False, (
                    f"{path} is {text.count(chr(10)) + 1} lines long and the target names "
                    f"line {last}"
                )
    return True, None


def check_drift(plan, repo, dry_run):
    """R-4.3: drift never silently invalidates the run and never silently proceeds."""
    planned = plan.meta.node.get("assessment_commit") if plan.meta else None
    current = head_commit(repo)
    record = {
        "planned_commit": planned,
        "current_commit": current,
        "drifted": False,
        "stale_items": {},
        "blocked_by_stale": {},
        "revalidated": 0,
    }
    if not planned or not current:
        record["note"] = (
            "no comparison was possible: the plan records "
            f"{planned!r} and HEAD is {current!r}. The run proceeds and this is recorded as "
            "a narrowing, because an unmeasured drift is not an absent one."
        )
        return record
    if current.startswith(planned) or planned.startswith(current):
        return record

    record["drifted"] = True
    stale = {}
    for item_id in sorted(plan.items, key=plan._item_key):
        node = plan.items[item_id].node
        if node.get("status") not in ("pending", "blocked-on-decision"):
            continue
        reasons = []
        for target in node.get("target") or []:
            if not isinstance(target, dict):
                continue
            ok, detail = target_still_there(repo, target, planned)
            record["revalidated"] += 1
            if not ok:
                reasons.append(detail)
        if reasons:
            stale[item_id] = "; ".join(reasons)

    # A stale item's dependents were never going to run either. R-6.2 handles that during the
    # loop; doing it here as well means the plan states the whole cost of the drift before a
    # single item is attempted, which is what R-4.3 asks the report to say.
    blocked = {}
    changed = True
    while changed:
        changed = False
        for item_id in sorted(plan.items, key=plan._item_key):
            if item_id in stale or item_id in blocked:
                continue
            if plan.items[item_id].node.get("status") not in ("pending", "blocked-on-decision"):
                continue
            upstream = [
                dependency
                for dependency in (plan.items[item_id].node.get("depends-on") or [])
                if dependency in stale or dependency in blocked
            ]
            if upstream:
                blocked[item_id] = ", ".join(sorted(upstream))
                changed = True

    record["stale_items"] = stale
    record["blocked_by_stale"] = blocked

    if not dry_run:
        for item_id, reason in sorted(stale.items(), key=lambda kv: plan._item_key(kv[0])):
            plan.set_field(
                "work-item", item_id, "diagnosis",
                f"Target moved. The plan was generated at commit {planned} and this run "
                f"started at {current}. Pre-flight revalidated this item's targets against "
                f"their recorded locations and found: {reason}. The item is marked stale "
                "rather than retargeted, because choosing a new target is a planning "
                "decision about what the item is now for, and R-2.1 does not let the "
                "executor make it. Re-plan against the code as it stands.",
            )
            plan.set_field("work-item", item_id, "status", "stale")
        for item_id, upstream in sorted(blocked.items(), key=lambda kv: plan._item_key(kv[0])):
            plan.set_field(
                "work-item", item_id, "diagnosis",
                f"Never attempted. This item depends on {upstream}, whose target(s) moved "
                "between planning and this run. R-6.2 marks the dependents of a stale item "
                "blocked-by-failure and the run continues with independent work rather than "
                "hanging. It becomes executable again once the item above it is re-planned.",
            )
            plan.set_field("work-item", item_id, "status", "blocked-by-failure")

    return record


# --------------------------------------------------------------------------------------
# R-4.4 — the baseline suite run
# --------------------------------------------------------------------------------------


def suite_command(plan, override):
    """The command that runs the whole suite, taken from the plan rather than guessed.

    Slice zero's `tests-pass` check is what the plan itself uses to prove the suite runs, so
    it is the suite command by the plan's own account. Falling back to the most frequently
    named command keeps this working on a plan whose slice zero checks something else.
    """
    if override:
        return override, "supplied on the command line"

    zero = plan.slices.get("S0")
    if zero is not None:
        for item_id in zero.node.get("items") or []:
            item = plan.items.get(item_id)
            if item is None:
                continue
            for check in item.node.get("completion-checks") or []:
                if isinstance(check, dict) and check.get("kind") == "tests-pass":
                    command = check.get("command")
                    if isinstance(command, str):
                        return command, f"slice zero's `tests-pass` check on {item_id}"

    counts = {}
    for block in plan.items.values():
        for check in block.node.get("completion-checks") or []:
            if isinstance(check, dict) and check.get("kind") == "tests-pass":
                command = check.get("command")
                if isinstance(command, str):
                    counts[command] = counts.get(command, 0) + 1
    if counts:
        best = max(sorted(counts), key=lambda c: counts[c])
        return best, f"the most frequently named `tests-pass` command ({counts[best]} items)"

    raise Stop(
        "no suite command could be found in the plan",
        """\
R-4.4 runs the existing suite once and records its failures, and the standing invariant of
R-5.4 is measured against that recording. Without it the executor cannot tell red it caused
from red it inherited, which is the difference between a bug it must fix and one that is not
its business.

The command is normally slice zero's `tests-pass` check. This plan has none, so supply it:

    python3 preflight.py <plan> --assessment <path> --test-command "<command>"

The command must run from the repository root and use repository-relative paths.""",
    )


def baseline_run(plan, repo, override, timeout):
    command, source = suite_command(plan, override)
    result = suite.run(command, repo, timeout)
    names, basis = suite.failing_tests(result.output)
    record = {
        "command": command,
        "command_source": source,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "seconds": round(result.seconds, 2),
        "inherited_failures": names,
        "failure_basis": basis,
    }
    if result.timed_out:
        record["note"] = (
            f"the suite timed out after {timeout}s, so no baseline exists. The standing "
            "invariant cannot be measured against a recording that was never made; every "
            "item's invariant check will be reported not-run with this as the reason."
        )
    elif not result.ok and basis == "unrecognised":
        record["note"] = (
            "the suite exited non-zero and no recognised reporter format was found in its "
            "output, so the run knows some tests fail and not which. Every failure the loop "
            "sees will be treated as inherited, which is the safe direction: it means the "
            "executor may miss red it caused rather than blaming it for red it did not."
        )
    return record


# --------------------------------------------------------------------------------------
# R-4.5 — the work branch
# --------------------------------------------------------------------------------------


def branch_name(plan, repo, override):
    if override:
        return override
    commit = (head_commit(repo) or "unknown")[:7]
    return f"test-execution/{commit}"


def create_branch(repo, name, force, dry_run):
    existing = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
    current = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    if existing.returncode == 0 and current != name and not force:
        raise Stop(
            f"the work branch `{name}` already exists",
            f"""\
R-4.5 creates the work branch. This one is already there, which means either a previous run
against this same commit, or a name collision.

The branch name is derived from the base commit, so a second run from the same starting state
wants the same name. That is deliberate — it makes a repeated run repeatable — and it means
this stop is the normal way a re-run announces itself.

Two ways forward, and they are different decisions:

  * Keep the previous run's work and continue on it:
        git switch {name}
    then run pre-flight again. It will not recreate the branch.

  * Discard the previous run and start over:
        python3 preflight.py <plan> --assessment <path> --force-branch
    which deletes `{name}` and recreates it at the current commit. Anything only on that
    branch is lost.

Pre-flight will not choose between those for you, because one of them destroys work.""",
        )

    if dry_run:
        return {"branch": name, "created": False, "note": "dry run: no branch was created"}

    if current == name:
        return {"branch": name, "created": False, "note": "already on the work branch"}
    if existing.returncode == 0 and force:
        git(repo, "branch", "-D", name, check=True)
    git(repo, "switch", "-c", name, check=True)
    return {"branch": name, "created": True}


# --------------------------------------------------------------------------------------
# Driving it
# --------------------------------------------------------------------------------------


def preflight(plan_path, assessment, repo, log_dir, branch, test_command, force_branch,
              timeout, dry_run):
    record = {"plan": plan_path, "assessment": assessment, "repository": repo,
              "dry_run": dry_run}

    check_not_already_executed(plan_path)
    check_lint(plan_path, assessment, "reviewed")

    plan = planio.Plan(plan_path, assessment=assessment, phase="executed",
                       lint_writes=not dry_run)
    record["approval"] = check_approved(plan)
    check_rewrites_applied(plan)

    dirty = working_tree_state(repo, [plan_path, log_dir, os.path.relpath(plan_path, repo)])
    if dirty:
        raise Stop(
            f"the working tree has {len(dirty)} uncommitted change(s)",
            "R-9.1 reads every item's actual footprint from the diff of that item's commit, "
            "and R-6.4 requires no item to end with the tree dirtier than it found it. "
            "Neither is measurable from a tree that was already dirty when the run started: "
            "the first commit would carry changes nobody planned, attributed to an item that "
            "did not make them.\n\n"
            "Uncommitted:\n"
            + "\n".join(f"    {path}" for path in dirty[:20])
            + ("\n    ..." if len(dirty) > 20 else "")
            + "\n\nCommit or stash them, then run pre-flight again. The plan file itself and "
            f"{log_dir} are exempt, because the run writes to both.",
        )

    skipped, written = mark_skipped(plan, dry_run)
    record["skipped"] = {"items": skipped, "written": written}

    record["drift"] = check_drift(plan, repo, dry_run)
    record["baseline"] = baseline_run(plan, repo, test_command, timeout)
    record["branch"] = create_branch(repo, branch_name(plan, repo, branch), force_branch,
                                     dry_run)
    record["base_commit"] = head_commit(repo)

    plan.reload()
    record["items"] = {
        item_id: block.node.get("status") for item_id, block in sorted(
            plan.items.items(), key=lambda kv: plan._item_key(kv[0])
        )
    }
    record["ready"] = sorted(
        (item_id for item_id, status in record["items"].items() if status == "pending"),
        key=plan._item_key,
    )
    record["narrowings"] = narrowings(record)
    return record


def narrowings(record):
    """Every way the run has already narrowed, before a single item was attempted (R-10.3)."""
    out = []
    skipped = record["skipped"]["items"]
    if skipped:
        out.append({
            "what": f"{len(skipped)} item(s) skipped for unresolved decisions",
            "cost": "Not attempted: " + "; ".join(
                f"{item} (waiting on {', '.join(blockers)})"
                for item, blockers in sorted(skipped.items())
            ) + ". Answering those decisions makes this work executable in a further run.",
        })
    drift = record["drift"]
    if drift.get("drifted"):
        out.append({
            "what": (
                f"the repository moved from {drift['planned_commit']} to "
                f"{(drift['current_commit'] or '?')[:7]} between planning and this run"
            ),
            "cost": (
                f"{len(drift['stale_items'])} item(s) marked stale because their targets "
                f"moved, and {len(drift['blocked_by_stale'])} blocked behind them. "
                + ("Stale: " + ", ".join(sorted(drift["stale_items"])) + ". " if drift["stale_items"] else "")
                + "Every other item's targets were revalidated and still resolve."
            ) if drift["stale_items"] or drift["blocked_by_stale"] else (
                f"All {drift['revalidated']} revalidated target(s) still resolve, so the "
                "drift cost this run nothing. It is recorded because an unstated drift is "
                "indistinguishable from none."
            ),
        })
    inherited = record["baseline"]["inherited_failures"]
    if inherited:
        out.append({
            "what": f"{len(inherited)} pre-existing test failure(s) inherited at pre-flight",
            "cost": (
                "Red before anything ran: " + ", ".join(inherited[:10])
                + (" ..." if len(inherited) > 10 else "")
                + ". The standing invariant is measured against this recording, so the "
                "executor is responsible for causing no new red rather than for repairing "
                "red it inherited. Repairing it was outside every item's footprint."
            ),
        })
    if record["baseline"].get("note"):
        out.append({
            "what": "the baseline suite run did not produce a usable failure list",
            "cost": record["baseline"]["note"],
        })
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--assessment", help="the assessment report, for the full lint")
    parser.add_argument("--repo", default=".", help="the repository root")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--branch", help="work branch name; derived from the base commit if omitted")
    parser.add_argument("--test-command", help="override the suite command taken from the plan")
    parser.add_argument("--force-branch", action="store_true",
                        help="delete and recreate an existing work branch, discarding it")
    parser.add_argument("--timeout", type=int, default=suite.DEFAULT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true",
                        help="check everything and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.assessment:
        print(
            "note: --assessment was not given, so the completeness and claim-enablement "
            "rules did not run. R-4.2 asks for the full lint. Pass it.",
            file=sys.stderr,
        )

    try:
        record = preflight(
            args.plan, args.assessment, args.repo, args.log_dir, args.branch,
            args.test_command, args.force_branch, args.timeout, args.dry_run,
        )
    except Stop as stop:
        print(f"STOP: {stop.message}\n", file=sys.stderr)
        print(stop.instruction, file=sys.stderr)
        return 2
    except planio.WriteRejected as rejected:
        print(f"STOP: {rejected}", file=sys.stderr)
        return 2

    if not args.dry_run:
        os.makedirs(os.path.join(args.repo, args.log_dir), exist_ok=True)
        target = os.path.join(args.repo, args.log_dir, "preflight.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
        record["written_to"] = os.path.join(args.log_dir, "preflight.json")

    if args.json:
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0

    print(f"pre-flight ok: {args.plan}")
    print(f"  approved by {record['approval']['by']} on {record['approval']['date']}")
    print(f"  branch {record['branch']['branch']} at {(record['base_commit'] or '?')[:7]}")
    print(f"  suite: {record['baseline']['command']}  ({record['baseline']['command_source']})")
    print(f"  inherited failures: {len(record['baseline']['inherited_failures'])}")
    drift = record["drift"]
    print(
        "  drift: "
        + ("none" if not drift["drifted"] else
           f"{len(drift['stale_items'])} stale, {len(drift['blocked_by_stale'])} blocked behind them")
    )
    print(f"  ready to execute: {len(record['ready'])} item(s)")
    for entry in record["narrowings"]:
        print(f"  narrowing: {entry['what']}")
    if args.dry_run:
        print("\n  (dry run: nothing was written and no branch was created)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

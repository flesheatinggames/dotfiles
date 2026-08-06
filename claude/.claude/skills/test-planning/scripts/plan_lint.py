#!/usr/bin/env python3
"""Validate a test plan. Deterministic, a script rather than an agent (R-11.1).

The planner fixes every failure this reports before the plan goes to the owner. The owner
never sees a plan that fails lint, which means a plan that was never linted is
indistinguishable from one that passed — so this script existing and running is itself part
of the gate.

It checks, in order:

* every block parses and validates against its schema;
* identifiers are unique and every reference resolves;
* the item and slice dependency graphs are acyclic;
* claims, labels, and sources are well formed, and every ``unit-tests`` item carries one;
* seam items name a catalog seam type and either a guard or a waiver;
* every completion check is machine-checkable as written;
* every escalation and decision blocks at least one item, and every blocked item names an
  existing blocker;
* **every assessment finding above the value line is covered or explicitly excluded** —
  R-11.3 calls this the most important rule, because it is what stops a top-tier finding
  being dropped silently;
* slice zero exists and precedes everything;
* footprints are well formed and the recorded wave schedule is consistent with them.

It also computes the wave schedule, so the planner does not have to and two runs cannot
disagree.

Usage:
    python3 plan_lint.py docs/test-plan.md --assessment docs/test-assessment.md
    python3 plan_lint.py docs/test-plan.md --waves        # print the schedule and exit
    python3 plan_lint.py docs/test-plan.md --json
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planlib  # noqa: E402
from planlib import Problem  # noqa: E402

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "test-assessment",
        "scripts",
    ),
)

TIER_ORDER = ["top", "high", "medium", "low"]

# A plan is linted at four points in its life, and a handful of rules mean different things
# at each. A freshly written plan must not carry resolutions, because writing one would be the
# planner deciding something it was not authorized to decide. After the review sitting the
# owner has written them in and re-runs the linter, at which point the same rule would reject
# the file it was meant to protect. After execution, stage three has written statuses the
# first two phases forbid. After close-out, stage four has written the owner's answer to every
# defect and the record of what each answer did to the branch.
PHASES = ("planned", "reviewed", "executed", "closed")
PRE_REVIEW_STATUSES = {"pending", "blocked-on-decision"}

# The phases at which stage three's writeback is present. `closed` is cumulative on `executed`:
# a closed plan carries everything an executed one does, plus the close-out records, so every
# execution rule runs at both.
POST_EXECUTION_PHASES = ("executed", "closed")

# The phases at which the owner has had a review sitting, so resolutions are legitimate.
POST_REVIEW_PHASES = ("reviewed", "executed", "closed")


# --------------------------------------------------------------------------------------
# Loading the assessment index
# --------------------------------------------------------------------------------------


# Notes the last `lint()` call wants the command line to print. A note is not a problem — it
# says what could not be checked, or what was checked against something other than the obvious
# file — so it cannot travel in `problems` without failing the plan. `lint()`'s two-value return
# is relied on by the execution stage, so it does not travel there either.
LAST_RUN_NOTES = []


def _git(cwd, *arguments):
    return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True)


def source_assessment_text(assessment_path, plan_path, phase):
    """The assessment this plan was built from, when that is not the one on disk.

    Returns ``(text, note)``, and ``(None, None)`` to mean "read the path as usual".

    Assessment reports are rewritten in place: the pipeline reuses one path across runs, and a
    second run's assessment legitimately drops recommendations the first one made and counts
    functions the first one could not reach. A plan at a finished phase is a historical record,
    so validating it against a later assessment reports the plan as broken when what actually
    changed is the document it is being measured against. The version committed alongside the
    plan is the one it was built from. `plan-meta.assessment_commit` cannot answer this: it
    records the commit whose *code* was assessed, which is typically before the report existed.
    """
    if phase not in POST_EXECUTION_PHASES:
        return None, None
    start = os.path.dirname(os.path.abspath(plan_path)) or "."
    top = _git(start, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None, None
    root = top.stdout.strip()
    relative_plan = os.path.relpath(os.path.abspath(plan_path), root)
    relative_assessment = os.path.relpath(os.path.abspath(assessment_path), root)
    found = _git(root, "log", "-1", "--format=%H", "--", relative_plan)
    commit = found.stdout.strip()
    if found.returncode != 0 or not commit:
        return None, None
    shown = _git(root, "show", f"{commit}:{relative_assessment}")
    if shown.returncode != 0:
        return None, None
    try:
        on_disk = open(assessment_path, encoding="utf-8").read()
    except OSError:
        return None, None
    if shown.stdout == on_disk:
        return None, None
    return shown.stdout, (
        f"{relative_assessment} has changed since this plan was last committed, so the "
        f"assessment-coupled checks ran against the version committed with the plan in "
        f"{commit[:7]} rather than the one on disk. A later run's assessment is not the one "
        f"this plan was built from."
    )


def load_assessment_index(path, problems, plan_path, text=None):
    """Read the ``assessment-index`` block out of an assessment report."""
    if text is None:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError as error:
            problems.append(
                Problem("assessment-unreadable", plan_path, 0, f"cannot read {path}: {error}")
            )
            return None
    for block in planlib.extract_blocks(text):
        if block.info.strip() == "json assessment-index":
            try:
                return json.loads(block.body)
            except json.JSONDecodeError as error:
                problems.append(
                    Problem(
                        "assessment-invalid",
                        path,
                        block.body_start_line + error.lineno - 1,
                        f"the assessment index is not valid JSON: {error.msg}",
                    )
                )
                return None
    problems.append(
        Problem(
            "assessment-unindexed",
            path,
            0,
            "the assessment report has no machine-readable index",
            "Run the test-assessment skill in backfill mode against this report first. "
            "See scripts/read_assessment.py for the full instruction.",
        )
    )
    return None


# --------------------------------------------------------------------------------------
# Graph helpers
# --------------------------------------------------------------------------------------


def find_cycle(graph):
    """Return a cycle as a list of nodes, or None. Deterministic: nodes visited in order."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    stack = []

    def visit(node):
        colour[node] = GREY
        stack.append(node)
        for neighbour in sorted(graph.get(node, [])):
            if neighbour not in colour:
                continue
            if colour[neighbour] == GREY:
                return stack[stack.index(neighbour):] + [neighbour]
            if colour[neighbour] == WHITE:
                found = visit(neighbour)
                if found:
                    return found
        stack.pop()
        colour[node] = BLACK
        return None

    for node in sorted(graph):
        if colour[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def slice_sort_key(slice_id):
    match = re.fullmatch(r"S([0-9]+)", slice_id)
    return (int(match.group(1)) if match else 10**9, slice_id)


def item_sort_key(item_id):
    match = re.fullmatch(r"WI-([0-9]+)", item_id)
    return (int(match.group(1)) if match else 10**9, item_id)


# --------------------------------------------------------------------------------------
# The wave computation
# --------------------------------------------------------------------------------------


def footprint_of(item_node):
    footprint = item_node.get("files-touched") or {}
    paths = set()
    for group in ("production", "test", "config"):
        for path in footprint.get(group) or []:
            if isinstance(path, str):
                paths.add(path)
    return paths


def compute_waves(slices, items_by_id):
    """Group slices into waves of pairwise-disjoint, dependency-free work.

    Deterministic by construction: slices are considered in ascending numeric identifier
    order at every step, so the same plan always produces the same schedule.

    A slice containing any item with ``global-effect: true`` takes a wave to itself. Slice
    zero's declared footprint is one configuration file, but rewriting repository-wide
    coverage configuration changes what every other slice measures — a footprint-only rule
    would happily schedule other slices alongside it.
    """
    slice_ids = sorted(slices, key=slice_sort_key)
    footprints = {}
    global_effect = {}
    for slice_id in slice_ids:
        paths = set()
        is_global = False
        for item_id in slices[slice_id].get("items") or []:
            item = items_by_id.get(item_id)
            if item is None:
                continue
            paths |= footprint_of(item)
            if item.get("global-effect") is True:
                is_global = True
        footprints[slice_id] = paths
        global_effect[slice_id] = is_global

    dependencies = {
        slice_id: set(slices[slice_id].get("depends-on") or []) & set(slice_ids)
        for slice_id in slice_ids
    }

    scheduled = set()
    waves = []
    remaining = list(slice_ids)

    while remaining:
        ready = [s for s in remaining if dependencies[s] <= scheduled]
        if not ready:
            break  # a cycle; reported separately
        wave = []
        used = set()
        reason = None
        for slice_id in ready:
            if global_effect[slice_id]:
                if not wave:
                    wave = [slice_id]
                    reason = (
                        f"{slice_id} carries an item with repository-wide effect, so it "
                        "occupies a wave alone regardless of its declared footprint"
                    )
                break
            if footprints[slice_id] & used:
                continue
            wave.append(slice_id)
            used |= footprints[slice_id]
        if not wave:
            wave = [ready[0]]
        waves.append({"wave": len(waves) + 1, "slices": wave, "reason": reason})
        scheduled |= set(wave)
        remaining = [s for s in remaining if s not in scheduled]

    for wave in waves:
        if wave["reason"] is None:
            wave["reason"] = (
                "pairwise disjoint footprints, no dependency edges between them"
                if len(wave["slices"]) > 1
                else "no other ready slice has a disjoint footprint"
            )
    return waves


# --------------------------------------------------------------------------------------
# The lint itself
# --------------------------------------------------------------------------------------


def check_ledger_consistency(ledger_path, items, claims, path, problems, anchor, run_record=None):
    """R-7.3 of the reporting document: the planner may not contradict the run ledger.

    Two rules, both narrow, and the narrowness is the requirement rather than caution. Section
    11 of that document defers the question of whether the planner should be bound as strictly
    as the assessment — which must discharge every open item — until a real multi-run sequence
    shows where planner-side drops actually occur. A rule invented before that evidence exists
    would be shaped by nothing.

    The asymmetry is also principled. An assessment establishes a repository's state, so an
    item absent from one has been asserted not to exist. A plan is a proposal about future
    work, and there are legitimate reasons to plan nothing about an open defect.
    """
    reporting = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "test-reporting",
        "scripts",
    )
    module_path = os.path.join(reporting, "ledger.py")
    if not os.path.isfile(module_path):
        problems.append(
            Problem(
                "reporting-skill-absent",
                path,
                anchor,
                "--ledger needs the test-reporting skill installed beside this one, and it is "
                f"not at {reporting}",
                "The run ledger is stage four's artifact and its reader is stage four's code. "
                "Install `test-reporting` alongside this skill rather than parsing the ledger "
                "here — a second reader would be a second opinion about what `open` means.",
            )
        )
        return

    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("test_reporting_ledger", module_path)
    ledger_module = importlib.util.module_from_spec(spec)
    sys.modules["test_reporting_ledger"] = ledger_module
    spec.loader.exec_module(ledger_module)

    try:
        data = ledger_module.load(ledger_path)
    except ledger_module.LedgerError as error:
        problems.append(Problem("ledger-unreadable", path, anchor, str(error)))
        return
    if data is None:
        problems.append(
            Problem(
                "ledger-absent",
                path,
                anchor,
                f"--ledger was given and there is no ledger at {ledger_path}",
                "A repository with no run ledger has had no closed run. Drop the flag.",
            )
        )
        return

    # The plan that *produced* the ledger's latest entry is not a plan the ledger binds. Linting
    # it against the ledger reports every one of its claims as already asserted — which is true
    # and useless, and a flag that produces a wall of true-and-useless output is a flag whose
    # next user turns it off. R-7.3 is about a plan for the *next* run.
    # Identity here is the run, not the path. Every run writes its plan to the same path, so a
    # path match also matches the *next* run's freshly written plan — which the ledger does bind,
    # and which would then be refused the very rules it exists to be checked against. A plan that
    # produced a run carries that run's `run-record`, and its `close_commit` names the run
    # exactly. A plan with no run record has produced nothing.
    latest = ledger_module.latest_run(data) or {}
    own = run_record or {}
    produced_latest = bool(own.get("close_commit")) and own["close_commit"] == latest.get("close_commit")
    if not produced_latest and own and latest.get("plan"):
        # Only for a plan that carries a run record at all: it may predate `close_commit` being
        # recorded, and then the path is the best identity left.
        produced_latest = os.path.abspath(latest["plan"]) == os.path.abspath(path)
    if produced_latest:
        problems.append(
            Problem(
                "ledger-is-this-plans-own",
                path,
                anchor,
                f"this plan produced the ledger's latest run ({latest.get('run_id')}), so the "
                "consistency rules were not run against it",
                "R-7.3 binds the plan for the next run, not the one the ledger was built from. "
                "Pass --ledger when linting a new plan against a repository that has already "
                "had a closed run.",
            )
        )
        return

    open_items = ledger_module.open_items(data)

    # Rule one: an item whose footprint touches a file carrying an open defect names it.
    defect_files = {}
    for item in open_items:
        if item.get("kind") != "defect":
            continue
        test = (item.get("detail") or {}).get("test") or {}
        for candidate in (test.get("file"),):
            if candidate:
                defect_files.setdefault(candidate, []).append(item["id"])
    for entry in data.get("defects", []):
        if entry.get("state") != "open":
            continue
        for location in entry.get("locations") or []:
            defect_files.setdefault(location.split(":")[0], []).append(entry.get("id"))

    for item_id, item in sorted(items.items(), key=lambda kv: item_sort_key(kv[0])):
        touched = footprint_of(item)
        named = set(item.get("known-defects") or [])
        owed = sorted({
            defect_id
            for file_path in touched
            for defect_id in defect_files.get(file_path, [])
        })
        missing = [defect_id for defect_id in owed if defect_id not in named]
        if missing:
            problems.append(
                Problem(
                    "unnamed-open-defect",
                    path,
                    item.line_of("files-touched", item.line),
                    f"{item_id} touches a file carrying open defect(s) "
                    f"{', '.join(missing)} and does not name them in `known-defects`",
                    "R-7.3: an open defect is not planned over as if undiscovered. The "
                    "executor will write tests in a file where something is already known to "
                    "be broken, and this field is the only way it finds that out.",
                )
            )

    # Rule two: a claim duplicating one the ledger already records at cited or ratified
    # authority is reported. Re-deriving it as new work counts the same assertion twice.
    held = {
        entry.get("id"): entry.get("authority")
        for entry in data.get("claims", [])
        if entry.get("authority") in ("cited", "ratified", "ratified-as-observed")
    }
    for claim_id, claim in sorted(claims.items()):
        authority = held.get(claim_id)
        if authority is None:
            continue
        if claim.get("label") in PLANNED_CLAIM_LABELS_LOCAL:
            problems.append(
                Problem(
                    "claim-already-asserted",
                    path,
                    claim.line_of("label", 1),
                    f"{claim_id} is labelled {claim.get('label')!r} and the run ledger "
                    f"already records it at {authority!r}",
                    "R-7.3: a claim already asserted at a given authority is not re-derived "
                    "as new work. Either this is the same claim, in which case it carries its "
                    "existing authority and the ratification list should not ask for it "
                    "again, or the identifier has been reused for something else — which is "
                    "worse, because every ledger reference to it now resolves to the wrong "
                    "statement.",
                )
            )


PLANNED_CLAIM_LABELS_LOCAL = {"cited", "pinned"}


def lint(plan_path, assessment_path=None, phase="planned", ledger_path=None):
    problems = []
    LAST_RUN_NOTES.clear()
    by_kind, load_problems, text = planlib.load_plan(plan_path)
    problems.extend(load_problems)
    if not by_kind:
        return problems, None

    # ---- schema ------------------------------------------------------------------
    for kind, blocks in sorted(by_kind.items()):
        schema = planlib.BLOCK_SCHEMAS[kind]
        for block in blocks:
            label = block.node.get("id") if isinstance(block.node.get("id"), str) else kind
            planlib.validate_mapping(
                block.node, schema, plan_path, problems, label, block.fence_line
            )

    meta = by_kind.get("plan-meta", [None])[0]
    meta_node = meta.node if meta else None

    items = {}
    item_blocks = {}
    for block in by_kind.get("work-item", []):
        item_id = block.node.get("id")
        if not isinstance(item_id, str):
            continue
        if item_id in items:
            problems.append(
                Problem("duplicate-id", plan_path, block.fence_line, f"work item {item_id} is defined twice")
            )
            continue
        items[item_id] = block.node
        item_blocks[item_id] = block

    slices = {}
    slice_blocks = {}
    for block in by_kind.get("slice", []):
        slice_id = block.node.get("id")
        if not isinstance(slice_id, str):
            continue
        if slice_id in slices:
            problems.append(
                Problem("duplicate-id", plan_path, block.fence_line, f"slice {slice_id} is defined twice")
            )
            continue
        slices[slice_id] = block.node
        slice_blocks[slice_id] = block

    claims = {}
    for block in by_kind.get("claim", []):
        claim_id = block.node.get("id")
        if not isinstance(claim_id, str):
            continue
        if claim_id in claims:
            problems.append(
                Problem("duplicate-id", plan_path, block.fence_line, f"claim {claim_id} is defined twice")
            )
            continue
        claims[claim_id] = block.node

    blockers = {}
    for kind in ("escalation", "decision"):
        for block in by_kind.get(kind, []):
            blocker_id = block.node.get("id")
            if isinstance(blocker_id, str):
                blockers[blocker_id] = block.node

    flagged = {
        b.node.get("id"): b.node for b in by_kind.get("flagged", []) if isinstance(b.node.get("id"), str)
    }

    # Anchor for problems about something being absent: the first block in the file, so
    # even "you are missing X" names a line the reader can navigate to.
    anchor = min(
        (block.fence_line for blocks in by_kind.values() for block in blocks), default=1
    )

    check_items(items, item_blocks, claims, slices, blockers, plan_path, problems, phase)
    check_claims(claims, by_kind, items, plan_path, problems, phase)
    check_slices(slices, slice_blocks, items, plan_path, problems, anchor, phase)
    check_blockers(by_kind, items, flagged, plan_path, problems, phase)
    check_execution(
        by_kind, meta, items, item_blocks, claims, plan_path, problems, phase, anchor
    )
    waves = check_waves(by_kind, slices, items, plan_path, problems, anchor)

    index = None
    if assessment_path:
        source_text, source_note = source_assessment_text(assessment_path, plan_path, phase)
        if source_note:
            LAST_RUN_NOTES.append(source_note)
        index = load_assessment_index(assessment_path, problems, plan_path, text=source_text)
    if index is not None:
        meta_line = meta.fence_line if meta else 0
        check_coverage_of_findings(index, meta_node, by_kind, items, plan_path, problems, meta_line)
        check_open_questions(index, meta_node, by_kind, plan_path, problems, meta_line)
        check_assessment_refs(index, by_kind, plan_path, problems)
        check_degradations(index, meta_node, plan_path, problems)
        check_claim_enablement(index, claims, items, item_blocks, plan_path, problems)
        check_scope(index, meta_node, claims, items, plan_path, problems, meta_line)

    if ledger_path:
        run_record_block = (by_kind.get("run-record") or [None])[0]
        check_ledger_consistency(
            ledger_path, items, claims, plan_path, problems, anchor,
            run_record=run_record_block.node if run_record_block else None,
        )

    return problems, waves


# --------------------------------------------------------------------------------------
# The claim-enablement rule (R-11.4)
# --------------------------------------------------------------------------------------

# Categories from the assessment's function-granularity testability section that mean a
# claim's target is not reachable by a unit test as things stand.
NEEDS_ENABLING = {"export-only", "needs-seam"}
NEVER_ASSERTABLE = {"integration-only", "excluded"}

# Raised as a hard stop rather than an ordinary failure: the remedy is a bounded piece of
# assessment work, not an edit to the plan, and saying so is more useful than a generic
# failure the planner cannot act on.
UNCLASSIFIED_RULE = "claim-target-unclassified"


def dependency_closure(items):
    """Every item's transitive `depends-on` set.

    Computed once for the whole plan rather than per claim. The graph is small and already
    known acyclic by the time this runs — `check_items` reports a cycle separately — but the
    visited set makes this terminate anyway, because a lint run on a cyclic plan should
    report the cycle rather than hang.
    """
    closure = {}

    def walk(item_id, seen):
        if item_id in closure:
            return closure[item_id]
        if item_id in seen:
            return set()
        seen = seen | {item_id}
        reached = set()
        for parent in items.get(item_id, {}).get("depends-on") or []:
            if not isinstance(parent, str):
                continue
            reached.add(parent)
            reached |= walk(parent, seen)
        closure[item_id] = reached
        return reached

    for item_id in items:
        walk(item_id, set())
    return closure


def index_testability(index):
    """Testability entries grouped by file, for resolving a claim's `path:line`."""
    by_file = {}
    for entry in index.get("testability") or []:
        if not isinstance(entry, dict):
            continue
        file = entry.get("file")
        if isinstance(file, str):
            by_file.setdefault(file, []).append(entry)
    return by_file


# How many lines above a function's first line still count as citing that function. Claims
# and recommendations routinely cite the docstring or comment block immediately above a
# function rather than its signature, and treating that as unresolvable would raise a hard
# stop telling the owner to backfill an assessment that already classifies the function. The
# real fix in those cases is two lines of citation style, which is not worth a round trip
# through stage one. Six lines covers a JSDoc or docstring header without reaching the
# previous function's body in any real file.
DOC_COMMENT_TOLERANCE = 6


def candidates_for(by_file, location):
    """The testability entries a claim location covers, and whether it named a line.

    A claim may name a bare `path` rather than a `path:line` — the claim schema allows it,
    and six real claims use it for behavior that spans a whole component. A bare path covers
    every function in the file, and the rule below treats the claim as assertable when any
    one of them is: a claim about a component's behavior is tested somewhere inside it, and
    demanding that every helper in the file be reachable would fail claims that are perfectly
    writable.

    Returns (entries, precise). `precise` is False for a bare path, which changes how a
    failure is worded — naming a file rather than a function.
    """
    if isinstance(location, str) and ":" not in location:
        return list(by_file.get(location, [])), False
    entry = resolve_location(by_file, location)
    return ([entry] if entry else []), True


def resolve_location(by_file, location):
    """The testability entry a `path:line` falls inside, or None.

    Where entries nest — a closure inside a function — the innermost wins, which is the one
    a claim at that line is actually about. Sorting by start line and taking the last match
    gives that without needing the ranges to be disjoint.

    A location just above a function resolves to it, per DOC_COMMENT_TOLERANCE.
    """
    if not isinstance(location, str) or ":" not in location:
        return None
    path, _, tail = location.rpartition(":")
    if not tail.isdigit():
        return None
    line = int(tail)
    entries = [
        entry
        for entry in by_file.get(path, [])
        if isinstance(entry.get("line"), int) and isinstance(entry.get("end_line"), int)
    ]
    inside = [e for e in entries if e["line"] <= line <= e["end_line"]]
    if inside:
        return max(inside, key=lambda e: e["line"])
    just_above = [e for e in entries if 0 < e["line"] - line <= DOC_COMMENT_TOLERANCE]
    if just_above:
        return min(just_above, key=lambda e: e["line"])
    return None


def check_claim_enablement(index, claims, items, item_blocks, path, problems):
    """Every claim an item asserts must be assertable by the time that item runs.

    Three things are checked, and they fail differently on purpose:

    - A claim whose target needs a seam, asserted by an item that does not depend on the
      item performing that seam. The test cannot reach the code when it runs.
    - A claim listed in some seam's `claims-enabled`, asserted by an item that does not
      depend on that seam. This is a violation **even where a weaker assertion might be
      possible without the seam**: the plan's bookkeeping and its dependency graph must
      agree, and a plan that records an enabling relationship it does not schedule is
      stating something untrue about itself.
    - A claim whose target the assessment never classified, which is a hard stop carrying
      the backfill instruction rather than a pass or a generic failure.

    Provenance, since this rule is preventive rather than a regression fix: the two defects
    it guards — claims asserted through an extraction no item performs, and a claim asserted
    in an early slice while its enabling seam sat in the final one — were found in a plan
    produced during a design conversation, not in any plan stored with this specification.
    """
    by_file = index_testability(index)
    scope = index.get("testability_scope") or {}
    complete = scope.get("complete") is True
    closure = dependency_closure(items)

    # Which items perform each assessment recommendation, so a `seam_ref` on a testability
    # entry can be turned into the item the asserting item must depend on.
    performs = {}
    for item_id, item in items.items():
        for ref in item.get("assessment-ref") or []:
            if isinstance(ref, str):
                performs.setdefault(ref, []).append(item_id)

    # Which seam item claims to unlock each claim.
    enables = {}
    for item_id, item in items.items():
        for claim_id in item.get("claims-enabled") or []:
            if isinstance(claim_id, str):
                enables.setdefault(claim_id, []).append(item_id)

    unclassified = {}

    for item_id, item in sorted(items.items(), key=lambda kv: item_sort_key(kv[0])):
        if item.get("type") not in ("unit-tests", "test-repair"):
            continue
        block = item_blocks.get(item_id)
        line = block.fence_line if block else 0
        claim_line = item.line_of("claims", line)
        reached = closure.get(item_id, set())

        for claim_id in item.get("claims") or []:
            claim = claims.get(claim_id)
            if claim is None:
                continue  # `dangling-claim` already reported it

            # Bookkeeping and the graph must agree, whatever the testability data says.
            for seam_item in enables.get(claim_id, []):
                if seam_item != item_id and seam_item not in reached:
                    problems.append(
                        Problem(
                            "claim-enabled-without-dependency",
                            path,
                            claim_line,
                            f"{item_id} asserts {claim_id}, which {seam_item} lists in its "
                            "`claims-enabled`, but {0} does not depend on {1}".format(
                                item_id, seam_item
                            ),
                            "Add the dependency, or remove the claim from the seam's "
                            "`claims-enabled` if the seam is not what makes it assertable. "
                            "This fails even where a weaker assertion might be possible "
                            "without the seam: the plan's bookkeeping and its dependency "
                            "graph must agree.",
                        )
                    )

            for location in claim.get("locations") or []:
                entries, precise = candidates_for(by_file, location)
                if not entries:
                    unclassified.setdefault(location, []).append(
                        (item_id, claim_id, claim_line)
                    )
                    continue

                verdicts = [
                    assertable(entry, item, item_id, reached, performs) for entry in entries
                ]
                if any(ok for ok, _ in verdicts):
                    continue

                if not precise:
                    problems.append(
                        Problem(
                            "claim-not-enabled",
                            path,
                            claim_line,
                            f"{item_id} asserts {claim_id} against the whole of {location}, "
                            f"and none of its {len(entries)} classified function(s) is "
                            "assertable when this item runs",
                            "; ".join(sorted({reason for _, reason in verdicts if reason})),
                        )
                    )
                    continue

                entry = entries[0]
                category = entry.get("category")
                function = entry.get("function", "?")
                rule = (
                    "claim-on-unassertable-target"
                    if category in NEVER_ASSERTABLE
                    else "claim-not-enabled"
                )
                problems.append(
                    Problem(
                        rule,
                        path,
                        claim_line,
                        f"{item_id} asserts {claim_id} against {location} ({function}), "
                        f"which the assessment classifies `{category}`"
                        + (
                            f" pending {entry.get('seam_ref')}"
                            if category in NEEDS_ENABLING
                            else ""
                        ),
                        verdicts[0][1],
                    )
                )

    report_unclassified(unclassified, complete, scope, path, problems)


def assertable(entry, item, item_id, reached, performs):
    """Whether one testability entry is assertable by this item. Returns (ok, reason)."""
    category = entry.get("category")
    if category in NEVER_ASSERTABLE:
        return False, (
            "An `excluded` function is outside the suite by the assessment's own exclusion "
            "list, and an `integration-only` function is one no catalog seam reaches — no "
            "seam is coming. Drop the claim, or take the exclusion back to the assessment."
        )
    if category not in NEEDS_ENABLING:
        return True, None

    seam_ref = entry.get("seam_ref")
    if seam_ref in (item.get("assessment-ref") or []):
        return True, None
    enabling = [c for c in performs.get(seam_ref, []) if c != item_id]
    if any(c in reached for c in enabling):
        return True, None
    if enabling:
        return False, (
            "The plan performs "
            + str(seam_ref)
            + " in "
            + ", ".join(sorted(enabling))
            + f", which {item_id} does not depend on. Add the dependency, or move this item "
            "into a later slice."
        )
    return False, (
        f"No item in the plan performs {seam_ref}. Either add one, or drop the claim — a "
        "test written against this function today cannot reach it."
    )


def report_unclassified(unclassified, complete, scope, path, problems):
    """One hard stop naming every location the assessment never classified.

    Aggregated into a single problem rather than one per claim, because the remedy is one
    piece of work: classify these functions. A dozen identical failures naming a dozen lines
    is the same instruction repeated, and it buries the rest of the lint output.
    """
    if not unclassified:
        return

    lines = []
    for location in sorted(unclassified):
        askers = sorted(
            f"{item} asserting {claim}" for item, claim, _ in unclassified[location]
        )
        lines.append(f"      {location} — needed by {', '.join(askers)}")
    listing = "\n".join(lines)

    # Anchored at the first asserting item's `claims` line rather than at line zero. The
    # failure is aggregated across items because the remedy is one piece of work, but a
    # problem with no line is a problem the planner cannot navigate to, and the fixture
    # README checks that none of them exists.
    anchor = min(
        line for members in unclassified.values() for _, _, line in members
    )

    if complete:
        problems.append(
            Problem(
                "claim-target-not-a-function",
                path,
                anchor,
                f"{len(unclassified)} claim location(s) resolve to no function in the "
                "assessment's testability data, which covers every function in the "
                "repository:\n" + listing,
                "`testability_scope.complete` is true, so the classified set is the whole "
                "inventory and these locations are not functions. Check the line numbers "
                "against the source — a claim pointing at an import or a blank line is a "
                "claim nobody can write a test for.",
            )
        )
        return

    tiers = ", ".join(scope.get("tiers") or []) or "none recorded"
    problems.append(
        Problem(
            UNCLASSIFIED_RULE,
            path,
            anchor,
            f"{len(unclassified)} claim location(s) fall outside the assessment's "
            f"classified set, so this plan cannot be checked for claim enablement:\n"
            + listing,
            "HARD STOP. The assessment classified "
            f"{scope.get('classified_functions', '?')} function(s) "
            f"(tiers: {tiers}), which does not include the functions above. Run the "
            "test-assessment skill in backfill mode against the report and ask it to "
            "classify exactly these locations:\n"
            + "\n".join(f"        {location}" for location in sorted(unclassified))
            + "\nThen re-run this linter. Do not widen the plan's scope to avoid the "
            "question, and do not assume the targets are reachable — assuming is what this "
            "rule exists to prevent.",
        )
    )


def check_items(items, item_blocks, claims, slices, blockers, path, problems, phase="planned"):
    graph = {item_id: [] for item_id in items}

    for item_id, item in sorted(items.items(), key=lambda kv: item_sort_key(kv[0])):
        block = item_blocks[item_id]
        line = block.fence_line
        item_type = item.get("type")

        for dependency in item.get("depends-on") or []:
            if dependency == item_id:
                problems.append(
                    Problem("self-dependency", path, item.line_of("depends-on", line), f"{item_id} depends on itself")
                )
            elif dependency not in items:
                problems.append(
                    Problem(
                        "dangling-dependency",
                        path,
                        item.line_of("depends-on", line),
                        f"{item_id} depends on {dependency}, which no work item defines",
                    )
                )
            else:
                graph[item_id].append(dependency)

        slice_id = item.get("slice")
        if isinstance(slice_id, str) and slice_id not in slices:
            problems.append(
                Problem(
                    "dangling-slice",
                    path,
                    item.line_of("slice", line),
                    f"{item_id} belongs to slice {slice_id}, which no slice block defines",
                )
            )
        elif isinstance(slice_id, str) and item_id not in (slices[slice_id].get("items") or []):
            problems.append(
                Problem(
                    "slice-membership",
                    path,
                    item.line_of("slice", line),
                    f"{item_id} says it belongs to {slice_id}, but {slice_id} does not list it",
                )
            )

        # ---- claims -------------------------------------------------------------
        item_claims = item.get("claims") or []
        enabled = item.get("claims-enabled") or []
        for claim_id in list(item_claims) + list(enabled):
            if claim_id not in claims:
                problems.append(
                    Problem(
                        "dangling-claim",
                        path,
                        item.line_of("claims", line),
                        f"{item_id} references claim {claim_id}, which no claim block defines",
                    )
                )

        verifies_removal = any(
            isinstance(c, dict)
            and (
                (c.get("kind") == "pattern-count" and c.get("expect") == 0)
                or (c.get("kind") == "file-exists" and c.get("absent") is True)
            )
            for c in (item.get("completion-checks") or [])
        )
        if not item_claims and (
            item_type == "unit-tests"
            or (item_type == "test-repair" and not verifies_removal)
        ):
            problems.append(
                Problem(
                    "no-claims",
                    path,
                    line,
                    f"{item_id} is a `{item_type}` item and carries no claims",
                    "Every item that writes or strengthens assertions must say what those "
                    "assertions verify (R-11.2). The one exception is a repair that removes "
                    "tests rather than strengthening them, which has no claims to carry — "
                    "that must instead verify the removal, with a `pattern-count` expecting "
                    "zero or a `file-exists` marked absent.",
                )
            )
        if item_type in ("infrastructure", "characterization") and item_claims:
            problems.append(
                Problem(
                    "unexpected-claims",
                    path,
                    item.line_of("claims", line),
                    f"{item_id} is a `{item_type}` item and carries claims",
                    "Infrastructure and characterization items carry no behavioral claims. "
                    "A characterization test pins current behavior without asserting it is "
                    "correct, which is what makes it scaffolding.",
                )
            )
        if enabled and item_type != "seam":
            problems.append(
                Problem(
                    "claims-enabled-misuse",
                    path,
                    item.line_of("claims-enabled", line),
                    f"{item_id} uses `claims-enabled` but is a `{item_type}` item",
                    "`claims-enabled` exists so a seam can point at the claims it unlocks "
                    "without those claims being ratified twice. Only seam items use it.",
                )
            )
        if item_type == "seam" and item_claims:
            problems.append(
                Problem(
                    "seam-carries-claims",
                    path,
                    item.line_of("claims", line),
                    f"{item_id} is a seam item carrying `claims`",
                    "Use `claims-enabled` instead. A seam that carries claims double-counts "
                    "them on the ratification list and asks the owner to approve each twice.",
                )
            )

        # ---- seams --------------------------------------------------------------
        if item_type == "seam":
            seam_type = item.get("seam-type")
            if seam_type not in (1, 2, 3, 4):
                problems.append(
                    Problem(
                        "seam-type",
                        path,
                        item.line_of("seam-type", line),
                        f"{item_id} names seam type {seam_type!r}; the catalog is closed at 1-4",
                    )
                )
            guard = item.get("guarded-by")
            waiver = item.get("guard-waiver")
            if guard is None and not waiver:
                problems.append(
                    Problem(
                        "seam-unguarded",
                        path,
                        line,
                        f"{item_id} is a seam with neither `guarded-by` nor `guard-waiver`",
                        "Refactoring untested code is where refactoring is most dangerous. "
                        "Name the characterization item that guards it, or say in writing "
                        "why no guard is required.",
                    )
                )
            elif guard is not None:
                if guard not in items:
                    problems.append(
                        Problem(
                            "dangling-guard",
                            path,
                            item.line_of("guarded-by", line),
                            f"{item_id} is guarded by {guard}, which no work item defines",
                        )
                    )
                elif items[guard].get("type") != "characterization":
                    problems.append(
                        Problem(
                            "guard-not-characterization",
                            path,
                            item.line_of("guarded-by", line),
                            f"{item_id} is guarded by {guard}, which is a "
                            f"`{items[guard].get('type')}` item, not a characterization item",
                        )
                    )
                elif guard not in (item.get("depends-on") or []):
                    problems.append(
                        Problem(
                            "guard-not-a-dependency",
                            path,
                            item.line_of("guarded-by", line),
                            f"{item_id} is guarded by {guard} but does not depend on it, so "
                            "nothing forces the guard to be written first",
                        )
                    )
                checks = item.get("completion-checks") or []
                if not any(
                    isinstance(c, dict) and c.get("kind") == "guard-holds" and c.get("item") == guard
                    for c in checks
                ):
                    problems.append(
                        Problem(
                            "missing-guard-check",
                            path,
                            item.line_of("completion-checks", line),
                            f"{item_id} is guarded by {guard} but carries no `guard-holds` "
                            f"check naming {guard}",
                            "The guard is only worth writing if the seam's completion "
                            "depends on it still passing.",
                        )
                    )
        elif item.get("seam-type") is not None:
            problems.append(
                Problem(
                    "seam-type-on-non-seam",
                    path,
                    item.line_of("seam-type", line),
                    f"{item_id} is a `{item_type}` item and carries `seam-type`",
                )
            )
        if item_type != "seam" and (item.get("guarded-by") or item.get("guard-waiver")):
            problems.append(
                Problem(
                    "guard-on-non-seam",
                    path,
                    line,
                    f"{item_id} is a `{item_type}` item and carries a guard field",
                )
            )

        # ---- completion checks ---------------------------------------------------
        checks = item.get("completion-checks") or []
        for i, check in enumerate(checks):
            check_line = checks.line_of(i) if isinstance(checks, planlib.SeqNode) else line
            planlib.validate_check(check, path, check_line, problems, f"{item_id} check {i + 1}")

        # ---- one mutation check, or one waiver, per asserted claim ---------------
        #
        # This replaces a per-item rule that required a `test-repair` item to carry a
        # mutation check *somewhere*. That rule was satisfied by one check on an item
        # asserting a dozen claims, which verifies one of them and says nothing about the
        # other eleven. The obligation belongs to the claim, because the claim is the thing
        # being verified.
        #
        # The removal exemption is untouched: an item that carries no claims — a repair that
        # deletes tests rather than strengthening them — has no claims to cover, so this loop
        # does nothing and the pattern-count or file-exists check remains what verifies it.
        if item_type in ("unit-tests", "test-repair"):
            check_mutation_coverage(item, item_claims, checks, item_id, path, line, problems)

        # ---- coverage delta ------------------------------------------------------
        # Each entry is an implied completion check. There is deliberately no separate
        # `coverage-delta` check kind: two copies of the same statement drift, and did.
        delta_line = item.line_of("coverage-delta", line)
        seen_targets = set()
        for i, delta in enumerate(item.get("coverage-delta") or []):
            if not isinstance(delta, dict):
                continue
            where = f"{item_id} coverage-delta {i + 1}"
            start, end = delta.get("from"), delta.get("to")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end <= start:
                problems.append(
                    Problem(
                        "coverage-not-a-delta",
                        path,
                        delta_line,
                        f"{where}: `to` ({end}) does not exceed `from` ({start}), so it is "
                        "satisfied without any work being done",
                    )
                )
            target_file = delta.get("file")
            if isinstance(target_file, str):
                if target_file.startswith("/") or target_file.startswith("~"):
                    problems.append(
                        Problem(
                            "absolute-coverage-target",
                            path,
                            delta_line,
                            f"{where}: names an absolute path {target_file!r}",
                        )
                    )
                key = (target_file, delta.get("metric"))
                if key in seen_targets:
                    problems.append(
                        Problem(
                            "duplicate-coverage-target",
                            path,
                            delta_line,
                            f"{where}: {target_file} / {delta.get('metric')} is declared twice "
                            "on the same item",
                        )
                    )
                seen_targets.add(key)
            # `baseline-source: none` is a paired rule, and both halves are checked. A `none`
            # beside a non-zero starting figure claims to have no baseline while stating one,
            # and a `none` with no note saying why is the shape this field takes when a
            # planner reaches for it to avoid recording where the number came from.
            if delta.get("baseline-source") == "none":
                if start not in (0, 0.0):
                    problems.append(
                        Problem(
                            "baseline-source-none",
                            path,
                            delta_line,
                            f"{where}: `baseline-source: none` with a non-zero `from` of {start}",
                            "`none` means the file does not exist when slice zero runs, so zero "
                            "is true by construction. A file that exists has a baseline slice "
                            "zero measures — say `slice-zero`.",
                        )
                    )
                note = delta.get("note")
                if not isinstance(note, str) or not re.search(r"creat", note, re.IGNORECASE):
                    problems.append(
                        Problem(
                            "baseline-source-none-unexplained",
                            path,
                            delta_line,
                            f"{where}: `baseline-source: none` without a `note` saying this "
                            "plan creates the file",
                            "`none` has exactly one legitimate use: a file that does not exist "
                            "when slice zero runs and is created by this plan. Say so in the "
                            "note, naming the item that creates it. Reasoning that zero is "
                            "true by construction because the repository has no tests is "
                            "wrong — that is true of the code, not of the measurement the "
                            "check runs against.",
                        )
                    )

        # ---- footprint -----------------------------------------------------------
        footprint = item.get("files-touched") or {}
        all_paths = []
        for group in ("production", "test", "config"):
            for entry in footprint.get(group) or []:
                if not isinstance(entry, str):
                    continue
                all_paths.append(entry)
                if entry.startswith("/") or entry.startswith("~"):
                    problems.append(
                        Problem(
                            "absolute-footprint",
                            path,
                            item.line_of("files-touched", line),
                            f"{item_id} declares an absolute path {entry!r} in its footprint",
                            "Footprints are repository-relative.",
                        )
                    )
                if "*" in entry or "?" in entry:
                    problems.append(
                        Problem(
                            "glob-footprint",
                            path,
                            item.line_of("files-touched", line),
                            f"{item_id} declares a glob {entry!r} in its footprint",
                            "A footprint is the concrete set of files the item will touch. "
                            "Two globs cannot be checked for disjointness, which is what the "
                            "footprint is for.",
                        )
                    )
        duplicates = {p for p in all_paths if all_paths.count(p) > 1}
        if duplicates:
            problems.append(
                Problem(
                    "footprint-duplicate",
                    path,
                    item.line_of("files-touched", line),
                    f"{item_id} lists {', '.join(sorted(duplicates))} in more than one "
                    "footprint group",
                )
            )
        if item_type in ("unit-tests", "characterization") and not (footprint.get("test") or []):
            problems.append(
                Problem(
                    "empty-test-footprint",
                    path,
                    item.line_of("files-touched", line),
                    f"{item_id} writes tests but declares no test files in its footprint",
                )
            )

        # ---- status and blockers -------------------------------------------------
        status = item.get("status")
        blocked_by = item.get("blocked-by") or []
        if status == "blocked-on-decision":
            if not blocked_by:
                problems.append(
                    Problem(
                        "blocked-without-blocker",
                        path,
                        item.line_of("status", line),
                        f"{item_id} is blocked-on-decision but names no `blocked-by`",
                        "R-6.3: a blocked item names the escalation or decision it waits on.",
                    )
                )
            for blocker in blocked_by:
                if blocker not in blockers:
                    problems.append(
                        Problem(
                            "dangling-blocker",
                            path,
                            item.line_of("blocked-by", line),
                            f"{item_id} is blocked by {blocker}, which no escalation or "
                            "decision block defines",
                        )
                    )
        elif blocked_by and not (phase in POST_EXECUTION_PHASES and status == "skipped"):
            # A `skipped` item keeps its `blocked-by`, and only at the executed phase. R-4.2
            # of the execution document marks the blocked items of an unresolved decision
            # `skipped`, and the blocker is the entire reason they were skipped — dropping it
            # would leave the run summary saying work was not attempted without saying what
            # would have unblocked it.
            problems.append(
                Problem(
                    "blocker-without-block",
                    path,
                    item.line_of("blocked-by", line),
                    f"{item_id} names `blocked-by` but its status is {status!r}",
                )
            )
        if phase not in POST_EXECUTION_PHASES and status not in PRE_REVIEW_STATUSES:
            problems.append(
                Problem(
                    "premature-status",
                    path,
                    item.line_of("status", line),
                    f"{item_id} has status {status!r} in a plan that has not been executed",
                    "A plan carries only `pending` and `blocked-on-decision` until stage "
                    "three runs. Pass --phase executed when linting a plan stage three has "
                    "written status back into.",
                )
            )

    cycle = find_cycle(graph)
    if cycle:
        problems.append(
            Problem(
                "item-cycle",
                path,
                item_blocks[cycle[0]].fence_line if cycle[0] in item_blocks else 1,
                "the work item dependency graph has a cycle: " + " -> ".join(cycle),
            )
        )


def check_mutation_coverage(item, item_claims, checks, item_id, path, line, problems):
    """Every asserted claim is covered by a mutation check or by exactly one waiver.

    Four failures, and they are genuinely different mistakes:

    - a claim covered by neither, which is the obligation itself;
    - a claim covered by both, which is a planner that wrote the check and then waived it
      anyway, or waived it and then wrote the check — either way one of the two is stale;
    - a waiver naming a claim the item does not carry, which is a stale reference or a claim
      that escaped the ledger;
    - a mutation check naming a claim the item does not carry, same reasoning from the other
      side.

    Only the mutation *coverage* is judged here. Whether the named edit really would falsify
    the named claim is a reading of two sentences, which is the owner's job at the gate and
    not something a script can do. What the script can guarantee is that the pairing exists
    and is unambiguous, which is what makes the owner's reading possible at all.
    """
    claims_present = list(item_claims or [])
    if not claims_present:
        return

    waivers = item.get("mutation-waiver") or []
    waiver_line = item.line_of("mutation-waiver", line)

    covered = {}
    for i, check in enumerate(checks):
        if not isinstance(check, dict) or check.get("kind") != "mutation":
            continue
        claim_id = check.get("claim")
        if not isinstance(claim_id, str):
            continue  # the check schema already reported the missing or malformed field
        covered.setdefault(claim_id, []).append(i + 1)
        if claim_id not in claims_present:
            problems.append(
                Problem(
                    "mutation-claim-not-carried",
                    path,
                    checks.line_of(i) if isinstance(checks, planlib.SeqNode) else line,
                    f"{item_id} check {i + 1} is a mutation for claim {claim_id}, which this "
                    "item does not assert",
                    "A mutation check verifies one of its own item's claims. If the claim "
                    "belongs to another item, the check belongs there too.",
                )
            )

    waived = {}
    for i, waiver in enumerate(waivers):
        if not isinstance(waiver, dict):
            continue
        claim_id = waiver.get("claim")
        if not isinstance(claim_id, str):
            continue  # the waiver schema already reported it
        waived.setdefault(claim_id, []).append(i + 1)
        if claim_id not in claims_present:
            problems.append(
                Problem(
                    "waiver-claim-not-carried",
                    path,
                    waiver_line,
                    f"{item_id} waives the mutation obligation for claim {claim_id}, which "
                    "this item does not assert",
                    "Either the waiver is left over from an earlier revision, or the claim "
                    "was dropped from `claims` and the waiver kept. Remove one.",
                )
            )

    for claim_id, positions in sorted(waived.items()):
        if len(positions) > 1:
            problems.append(
                Problem(
                    "waiver-duplicate",
                    path,
                    waiver_line,
                    f"{item_id} waives claim {claim_id} {len(positions)} times",
                    "One waiver per claim. Two waivers with different reasons is two "
                    "different admissions about one claim, and the owner cannot ratify both.",
                )
            )

    for claim_id in claims_present:
        has_check = claim_id in covered
        has_waiver = claim_id in waived
        if has_check and has_waiver:
            problems.append(
                Problem(
                    "mutation-check-and-waiver",
                    path,
                    waiver_line,
                    f"{item_id}: claim {claim_id} carries both a mutation check (check "
                    f"{covered[claim_id][0]}) and a waiver saying it admits none",
                    "One of the two is stale. A claim with a falsifying edit does not need "
                    "a waiver, and a claim that genuinely admits none cannot have a check.",
                )
            )
        elif not has_check and not has_waiver:
            problems.append(
                Problem(
                    "claim-without-mutation",
                    path,
                    item.line_of("claims", line),
                    f"{item_id}: claim {claim_id} is asserted with no mutation check that "
                    "falsifies it and no waiver",
                    "R-7.1 requires one or the other for every asserted claim. A "
                    "well-formed claim nearly dictates its mutation: a claim that a query "
                    "is scoped names the filter to delete, a claim of a fallback names the "
                    "default to change. Where none exists, record a "
                    "`mutation-waiver` entry with the reason.",
                )
            )


def check_claims(claims, by_kind, items, path, problems, phase="planned"):
    referenced = set()
    for item in items.values():
        referenced |= set(item.get("claims") or [])
        referenced |= set(item.get("claims-enabled") or [])

    # A claim an answer would add is referenced, conditionally. Without this the `add-claims`
    # mechanism is unusable for its main purpose: a decision whose two answers imply two
    # different claims has to define both, and the one the plan is not written as belongs to
    # no item until the owner answers. Reporting it as an orphan tells the planner to delete
    # the very thing that lets the owner see what each answer costs.
    for kind in ("escalation", "decision"):
        for block in by_kind.get(kind, []):
            for option in block.node.get("options") or []:
                if not isinstance(option, dict):
                    continue
                for effect in option.get("effect") or []:
                    if isinstance(effect, dict):
                        referenced |= {
                            c for c in (effect.get("add-claims") or []) if isinstance(c, str)
                        }

    blocks_by_id = {b.node.get("id"): b for b in by_kind.get("claim", [])}

    for claim_id, claim in sorted(claims.items()):
        block = blocks_by_id.get(claim_id)
        line = block.fence_line if block else 0
        if claim_id not in referenced:
            problems.append(
                Problem(
                    "orphan-claim",
                    path,
                    line,
                    f"claim {claim_id} is defined but no work item references it",
                    "Either an item should carry it, or it belongs in the backlog rather "
                    "than on the ratification list the owner has to work through.",
                )
            )

        source = claim.get("source") or {}
        label = claim.get("label")

        # The label vocabulary is phase-gated. `check_claims` has always taken a `phase` and
        # never used it; the two execution-stage labels are what make the gate matter, since
        # without it a planner could emit a `disputed` claim in a plan nobody has run — which
        # asserts that execution found something before execution happened.
        allowed = planlib.CLAIM_LABELS_BY_PHASE.get(phase, planlib.CLAIM_LABELS)
        if isinstance(label, str) and label in planlib.CLAIM_LABELS and label not in allowed:
            if label in planlib.EXECUTION_CLAIM_LABELS:
                fix = (
                    "`disputed` and `ratified-as-observed` are execution-stage and close-out "
                    "writes. Pass --phase executed when linting a plan stage three has "
                    "written back into."
                )
            else:
                fix = (
                    "Ratification only ever results from owner review (R-5.1). Pass "
                    "--phase reviewed when linting after the review sitting."
                )
            problems.append(
                Problem(
                    "premature-claim-label",
                    path,
                    claim.line_of("label", line),
                    f"{claim_id} is labelled {label!r} in a plan at phase {phase!r}, which "
                    f"allows only {', '.join(sorted(allowed))}",
                    fix,
                )
            )

        if label == "cited":
            if source.get("kind") != "document":
                problems.append(
                    Problem(
                        "cited-without-document",
                        path,
                        claim.line_of("source", line),
                        f"{claim_id} is labelled `cited` but its source is not a document",
                        "Cited means traced to a requirements or specification document. "
                        "A claim read from the code is `pinned`.",
                    )
                )
            if not (source.get("quote") or "").strip():
                problems.append(
                    Problem(
                        "cited-without-quote",
                        path,
                        claim.line_of("source", line),
                        f"{claim_id} is labelled `cited` but carries no quote",
                        "Absolute rule 6: a cited claim carries its quote inline, because "
                        "the reviewer must be able to check the label without opening the "
                        "repository. An unquoted citation is the one thing the human gate "
                        "cannot check cheaply.",
                    )
                )
            if not (source.get("location") or "").strip():
                problems.append(
                    Problem(
                        "cited-without-location",
                        path,
                        claim.line_of("source", line),
                        f"{claim_id} is labelled `cited` but names no document location",
                    )
                )
        elif label == "pinned":
            if source.get("kind") != "code":
                problems.append(
                    Problem(
                        "pinned-without-code",
                        path,
                        claim.line_of("source", line),
                        f"{claim_id} is labelled `pinned` but its source is not code",
                    )
                )
            if not (source.get("location") or "").strip():
                problems.append(
                    Problem(
                        "pinned-without-location",
                        path,
                        claim.line_of("source", line),
                        f"{claim_id} is labelled `pinned` but names no code location",
                    )
                )
        elif label == "ratified":
            if not claim.get("ratified-by"):
                problems.append(
                    Problem(
                        "ratified-without-owner",
                        path,
                        claim.line_of("label", line),
                        f"{claim_id} is labelled `ratified` but names nobody who ratified it",
                        "An approval with no approver is not an approval. Add `ratified-by` "
                        "and `ratified-on`. A freshly written plan should contain no ratified "
                        "claims at all: ratification only ever results from owner review "
                        "(R-5.1).",
                    )
                )
        elif label == "disputed":
            # A dispute is only meaningful about a claim that was pinned. A cited claim whose
            # test fails is a defect in the code, which is a registry entry and a red test —
            # a different mechanism with a different consequence, and mislabelling one as the
            # other would quietly downgrade a deploy-blocking finding to a note.
            if source.get("kind") != "code":
                problems.append(
                    Problem(
                        "disputed-without-code",
                        path,
                        claim.line_of("label", line),
                        f"{claim_id} is labelled `disputed` but its source is not code",
                        "A dispute impeaches the planner's reading of the code, so it applies "
                        "to a claim that was pinned. A cited claim whose faithful test fails "
                        "is a defect: a registry entry and a committed red test.",
                    )
                )
        elif label == "ratified-as-observed":
            if not claim.get("ratified-by"):
                problems.append(
                    Problem(
                        "ratified-without-owner",
                        path,
                        claim.line_of("label", line),
                        f"{claim_id} is labelled `ratified-as-observed` but names nobody who "
                        "ruled on it",
                        "This label records that the owner judged a cited requirement wrong "
                        "and accepted the observed behavior instead. That is a decision with "
                        "an author. Add `ratified-by` and `ratified-on`.",
                    )
                )

        for location in claim.get("locations") or []:
            if isinstance(location, str) and (location.startswith("/") or location.startswith("~")):
                problems.append(
                    Problem(
                        "absolute-claim-location",
                        path,
                        claim.line_of("locations", line),
                        f"{claim_id} names an absolute location {location!r}",
                    )
                )


def check_slices(slices, slice_blocks, items, path, problems, anchor=1, phase="planned"):
    if not slices:
        problems.append(Problem("no-slices", path, anchor, "the plan contains no slices"))
        return

    if "S0" not in slices:
        problems.append(
            Problem(
                "no-slice-zero",
                path,
                anchor,
                "there is no slice S0",
                "R-8.2: slice zero is mandatory and contains only infrastructure. Where a "
                "test framework already exists it degrades to verify-and-baseline, but it "
                "still exists.",
            )
        )
    else:
        zero = slices["S0"]
        line = slice_blocks["S0"].fence_line
        if zero.get("depends-on"):
            problems.append(
                Problem(
                    "slice-zero-depends",
                    path,
                    zero.line_of("depends-on", line),
                    "slice zero depends on another slice; it precedes everything",
                )
            )
        for item_id in zero.get("items") or []:
            item = items.get(item_id)
            if item is not None and item.get("type") != "infrastructure":
                problems.append(
                    Problem(
                        "slice-zero-contents",
                        path,
                        line,
                        f"slice zero contains {item_id}, a `{item.get('type')}` item",
                        "Slice zero contains only infrastructure items and carries no "
                        "behavioral claims.",
                    )
                )

    graph = {slice_id: [] for slice_id in slices}
    for slice_id, node in sorted(slices.items(), key=lambda kv: slice_sort_key(kv[0])):
        line = slice_blocks[slice_id].fence_line
        for dependency in node.get("depends-on") or []:
            if dependency == slice_id:
                problems.append(
                    Problem("self-dependency", path, line, f"{slice_id} depends on itself")
                )
            elif dependency not in slices:
                problems.append(
                    Problem(
                        "dangling-dependency",
                        path,
                        node.line_of("depends-on", line),
                        f"{slice_id} depends on {dependency}, which no slice defines",
                    )
                )
            else:
                graph[slice_id].append(dependency)

        for item_id in node.get("items") or []:
            item = items.get(item_id)
            if item is None:
                problems.append(
                    Problem(
                        "dangling-item",
                        path,
                        node.line_of("items", line),
                        f"{slice_id} lists {item_id}, which no work item defines",
                    )
                )
            elif item.get("slice") != slice_id:
                problems.append(
                    Problem(
                        "slice-membership",
                        path,
                        node.line_of("items", line),
                        f"{slice_id} lists {item_id}, but {item_id} says it belongs to "
                        f"{item.get('slice')!r}",
                    )
                )

        if slice_id != "S0" and "S0" not in (node.get("depends-on") or []):
            problems.append(
                Problem(
                    "slice-zero-not-first",
                    path,
                    node.line_of("depends-on", line),
                    f"{slice_id} does not depend on S0",
                    "Slice zero precedes everything, and the wave schedule is computed from "
                    "the dependency edges, so the edge has to be written down.",
                )
            )

    cycle = find_cycle(graph)
    if cycle:
        problems.append(
            Problem(
                "slice-cycle",
                path,
                slice_blocks[cycle[0]].fence_line,
                "the slice dependency graph has a cycle: " + " -> ".join(cycle),
            )
        )

    check_risk_order(slices, slice_blocks, items, path, problems, phase)

    # Item dependencies must not cross slices in the wrong direction.
    for item_id, item in sorted(items.items(), key=lambda kv: item_sort_key(kv[0])):
        home = item.get("slice")
        for dependency in item.get("depends-on") or []:
            other = items.get(dependency)
            if other is None or home not in slices:
                continue
            away = other.get("slice")
            if away == home or away not in slices:
                continue
            if away not in (slices[home].get("depends-on") or []):
                problems.append(
                    Problem(
                        "cross-slice-dependency",
                        path,
                        item.line_of("depends-on", anchor),
                        f"{item_id} in {home} depends on {dependency} in {away}, but {home} "
                        f"does not declare a dependency on {away}",
                        "An item dependency that crosses slices is a slice dependency. The "
                        "wave schedule is computed from slice edges, so an undeclared one "
                        "would let the two slices run concurrently.",
                    )
                )


def check_risk_order(slices, slice_blocks, items, path, problems, phase="planned"):
    """R-8.5: slice order follows the risk ranking, with exactly two permitted deviations.

    A slice's severity is the severity of its most severe item. A violation is a slice
    that is more severe than the one before it, which means either the severe slice was
    demoted or the mild one was pulled forward. Exactly one of those two slices must carry
    the matching deviation and its justification.
    """
    ordered = [s for s in sorted(slices, key=slice_sort_key) if s != "S0"]

    def severity(slice_id):
        tiers = [
            items[item_id].get("risk-tier")
            for item_id in (slices[slice_id].get("items") or [])
            if item_id in items and items[item_id].get("risk-tier") in TIER_ORDER
        ]
        if not tiers:
            return len(TIER_ORDER)
        return min(TIER_ORDER.index(tier) for tier in tiers)

    for earlier, later in zip(ordered, ordered[1:]):
        if severity(later) >= severity(earlier):
            continue
        deviations = {
            slice_id: (slices[slice_id].get("deviation") or {}).get("kind")
            for slice_id in (earlier, later)
        }
        if deviations[later] == "demoted-fully-blocked" or deviations[earlier] == "pulled-forward-for-seam":
            continue
        problems.append(
            Problem(
                "risk-order",
                path,
                slice_blocks[later].fence_line,
                f"{later} is `{TIER_ORDER[severity(later)]}` tier and follows {earlier}, "
                f"which is only `{TIER_ORDER[severity(earlier)]}` tier, with no deviation "
                "recorded on either",
                "R-8.5 permits two deviations from risk order: pulling a slice forward "
                "because a later slice depends on its seam, and demoting a fully blocked "
                "slice. Record the one that applies, with its justification, or reorder.",
            )
        )

    for slice_id in ordered:
        deviation = slices[slice_id].get("deviation")
        if not isinstance(deviation, dict) or deviation.get("kind") != "demoted-fully-blocked":
            continue
        members = [items[i] for i in (slices[slice_id].get("items") or []) if i in items]
        # `skipped` is the executed-phase form of the same fact. R-4.2 of the execution
        # document marks the blocked items of an unresolved decision `skipped`, so a slice
        # that was fully blocked at review is fully skipped after the run — and holding it to
        # `blocked-on-decision` afterwards would fail the demotion for having been honoured.
        blocked = {"blocked-on-decision"} | (
            {"skipped"} if phase in POST_EXECUTION_PHASES else set()
        )
        if members and not all(m.get("status") in blocked for m in members):
            problems.append(
                Problem(
                    "demotion-not-blocked",
                    path,
                    slice_blocks[slice_id].fence_line,
                    f"{slice_id} claims the `demoted-fully-blocked` deviation, but not every "
                    "item in it is blocked-on-decision"
                    + (" or skipped" if phase in POST_EXECUTION_PHASES else ""),
                    "A partly executable slice is not fully blocked, so the demotion is not "
                    "the permitted one. **The usual cause is a resolution rather than a "
                    "drafting error**: the owner answered the decision that blocked this "
                    "slice, its items moved to `pending`, and the deviation that justified "
                    "demoting it is now describing something that stopped being true. Remove "
                    "the `deviation` and put the slice back at its risk position, which is "
                    "what answering the decision was for.",
                )
            )


def check_blockers(by_kind, items, flagged, path, problems, phase="planned"):
    for kind in ("escalation", "decision"):
        for block in by_kind.get(kind, []):
            node = block.node
            blocker_id = node.get("id")
            line = block.fence_line
            blocked = node.get("blocks") or []
            # Items some answer to this blocker removes from the plan entirely. Once the owner
            # has answered, an item named here may legitimately be gone — and `blocks` keeps
            # naming it, because that list is the record of what the answer did.
            #
            # This is only reachable when a resolved option drops the *last* item a blocker
            # blocks, which is why no plan met it until one did: following the plan's own
            # resolution instruction produced a plan the linter rejected. The check is
            # deliberately weak — any option offering to drop the item explains its absence —
            # because verifying that the *chosen* answer's rewrite was applied is pre-flight's
            # job (execution R-4.2) and duplicating it here would put the resolution-parsing
            # convention in two places.
            droppable = set()
            if node.get("resolution") and phase in POST_REVIEW_PHASES:
                for option in node.get("options") or []:
                    if not isinstance(option, dict):
                        continue
                    for effect in option.get("effect") or []:
                        if isinstance(effect, dict) and effect.get("drop") is True:
                            if isinstance(effect.get("item"), str):
                                droppable.add(effect["item"])

            for item_id in blocked:
                if item_id not in items and item_id not in droppable:
                    problems.append(
                        Problem(
                            "dangling-blocked-item",
                            path,
                            node.line_of("blocks", line),
                            f"{blocker_id} blocks {item_id}, which no work item defines",
                        )
                    )
                elif item_id in items and blocker_id not in (
                    items[item_id].get("blocked-by") or []
                ) and not (node.get("resolution") and phase in POST_REVIEW_PHASES):
                    # The exemption is what makes a resolved plan lintable at all. Once the
                    # owner answers a blocker, `resolved-but-still-blocked` tells the item to
                    # drop it from `blocked-by` — and the blocker keeps its `blocks` list,
                    # because that list is the record of what the answer unlocked and stage
                    # four reports on it. Without the exemption those two rules contradict
                    # each other and no reviewed plan can pass, which is a defect this stage
                    # only met once an executed plan existed to lint.
                    problems.append(
                        Problem(
                            "asymmetric-block",
                            path,
                            node.line_of("blocks", line),
                            f"{blocker_id} blocks {item_id}, but {item_id} does not name "
                            f"{blocker_id} in `blocked-by`",
                        )
                    )
            check_option_effects(node, blocker_id, blocked, items, path, line, problems)

            if node.get("resolution") and phase == "planned":
                problems.append(
                    Problem(
                        "premature-resolution",
                        path,
                        node.line_of("resolution", line),
                        f"{blocker_id} already carries a resolution",
                        "Resolutions are written by the owner at review. A plan that arrives "
                        "with them filled in has decided something it was not authorized to "
                        "decide. Pass --phase reviewed when linting after the review sitting.",
                    )
                )
            if node.get("resolution") and phase in POST_REVIEW_PHASES:
                for item_id in blocked:
                    item = items.get(item_id)
                    if item is not None and item.get("status") == "blocked-on-decision":
                        problems.append(
                            Problem(
                                "resolved-but-still-blocked",
                                path,
                                item.line_of("status", 1),
                                f"{blocker_id} has been resolved but {item_id} is still "
                                "`blocked-on-decision`",
                                "Move the item to `pending` and drop the blocker from its "
                                "`blocked-by`. Leaving it blocked means stage three skips work "
                                "the owner just unblocked.",
                            )
                        )

    for flag_id, node in flagged.items():
        for item in items.values():
            if flag_id in (item.get("blocked-by") or []):
                problems.append(
                    Problem(
                        "flagged-blocks-item",
                        path,
                        item.line_of("blocked-by", 1),
                        f"{item.get('id')} is blocked by {flag_id}, which is a flagged note",
                        "A flagged item is documented behavior with no implementing code. "
                        "It is a note to the owner, never a work item and never a blocker: "
                        "writing the missing production code is outside this skill's "
                        "charter, so nothing here can wait on it.",
                    )
                )


def check_option_effects(node, blocker_id, blocked, items, path, line, problems):
    """Validate the per-option rewrites, and catch conditional outcomes stated in prose.

    An option with no ``effect`` means the blocked items execute exactly as written under
    that answer, which is the common case. An option that *does* change something must say
    so here rather than in an item's prose: R-7.1 requires each completion check to be
    machine-checkable as written, and a check carrying a sentence that says it applies only
    under one answer is not — the executor has to interpret, which is precisely what the
    plan exists to prevent.
    """
    blocked_set = set(blocked)
    covered = {}

    for i, option in enumerate(node.get("options") or []):
        if not isinstance(option, dict):
            continue
        option_id = option.get("id")
        where = f"{blocker_id} option {option_id or i + 1}"
        for effect in option.get("effect") or []:
            if not isinstance(effect, dict):
                continue
            item_id = effect.get("item")
            if not isinstance(item_id, str):
                continue
            covered.setdefault(option_id, set()).add(item_id)

            if item_id not in blocked_set:
                problems.append(
                    Problem(
                        "effect-on-unblocked-item",
                        path,
                        line,
                        f"{where} rewrites {item_id}, which {blocker_id} does not block",
                        "An answer may only rewrite the items that wait on it. Add the item "
                        "to `blocks`, or move the rewrite to the blocker that owns it.",
                    )
                )
                continue

            item = items.get(item_id)
            if effect.get("drop") is True:
                for key in ("set", "remove-checks", "remove-claims", "add-claims"):
                    if effect.get(key):
                        problems.append(
                            Problem(
                                "effect-drop-conflict",
                                path,
                                line,
                                f"{where} both drops {item_id} and rewrites its `{key}`",
                                "An item that does not exist under this answer has nothing "
                                "to rewrite. Keep `drop` alone.",
                            )
                        )
                continue

            for key in effect.get("unset") or []:
                if key not in planlib.WORK_ITEM_SCHEMA:
                    problems.append(
                        Problem(
                            "effect-unknown-field",
                            path,
                            line,
                            f"{where} unsets `{key}` on {item_id}, which is not a work item field",
                        )
                    )
                elif key in planlib.WORK_ITEM_SCHEMA["_required"]:
                    problems.append(
                        Problem(
                            "effect-unsets-required",
                            path,
                            line,
                            f"{where} unsets `{key}` on {item_id}, which every work item must "
                            "carry",
                            "Use `set` to change its value, or `drop` the item entirely.",
                        )
                    )
                elif item is not None and key not in item:
                    problems.append(
                        Problem(
                            "effect-unsets-absent",
                            path,
                            line,
                            f"{where} unsets `{key}` on {item_id}, which does not carry it",
                        )
                    )

            for key, value in (effect.get("set") or {}).items():
                spec = planlib.WORK_ITEM_SCHEMA.get(key)
                if spec is None:
                    problems.append(
                        Problem(
                            "effect-unknown-field",
                            path,
                            line,
                            f"{where} sets `{key}` on {item_id}, which is not a work item field",
                            "A misspelled field here is silently ignored at review, which is "
                            "the failure this rule exists to catch.",
                        )
                    )
                    continue
                planlib._check_field(
                    value, spec, path, line, problems, f"{where} set.{key} on {item_id}"
                )

            if item is None:
                continue
            for kind in effect.get("remove-checks") or []:
                present = {
                    c.get("kind")
                    for c in (item.get("completion-checks") or [])
                    if isinstance(c, dict)
                }
                if kind not in present:
                    problems.append(
                        Problem(
                            "effect-removes-absent-check",
                            path,
                            line,
                            f"{where} removes a `{kind}` check from {item_id}, which has none",
                        )
                    )
            item_claims = set(item.get("claims") or []) | set(item.get("claims-enabled") or [])
            for claim_id in effect.get("remove-claims") or []:
                if claim_id not in item_claims:
                    problems.append(
                        Problem(
                            "effect-removes-absent-claim",
                            path,
                            line,
                            f"{where} removes claim {claim_id} from {item_id}, which does not "
                            "carry it",
                        )
                    )

    # Which answers change nothing anywhere. An option with no `effect` on any item means
    # every blocked item executes exactly as written under that answer — so prose naming it
    # cannot be describing an answer-specific outcome, and can only be saying which answer the
    # item was written as. Saying that is what the skill's own procedure asks for: "Write the
    # item out as one answer, say in its justification which one, and let the others state
    # their diffs." Without this exemption the rule fires on the prescribed practice, which is
    # how it was found — on the first real plan that used `effect` at all.
    inert = {
        option.get("id")
        for option in node.get("options") or []
        if isinstance(option, dict) and not option.get("effect")
    }

    # The rule that catches what prose was hiding.
    for item_id in sorted(blocked_set):
        item = items.get(item_id)
        if item is None:
            continue
        prose = " ".join(
            str(item.get(field) or "") for field in ("justification", "notes", "title")
        )
        for option in node.get("options") or []:
            if not isinstance(option, dict):
                continue
            option_id = option.get("id")
            if not isinstance(option_id, str) or option_id not in prose:
                continue
            if option_id in inert:
                continue
            if item_id in covered.get(option_id, set()):
                continue
            problems.append(
                Problem(
                    "conditional-prose",
                    path,
                    item.line_of("justification", item.line_of("notes", line)),
                    f"{item_id} describes in prose what happens to it under {option_id}, but "
                    f"{option_id} carries no `effect` for it",
                    "State the difference as an `effect` on that option so the executor does "
                    "not have to interpret it, or reword the prose so it does not describe an "
                    "answer-specific outcome. A completion check qualified by a sentence is "
                    "not machine-checkable as written.",
                )
            )


# --------------------------------------------------------------------------------------
# The execution phase
# --------------------------------------------------------------------------------------
#
# `--phase executed` began as pure relaxation: it permitted the wider status and claim-label
# vocabularies and required nothing in exchange. That is the wrong shape. An executed plan
# claiming an item is `done` with no commit and no recorded actuals is exactly the kind of
# embellished record R-11 of the execution document forbids, and nothing was checking for it.
# The phase that allows the executor to write is the phase that should insist it wrote
# everything.
#
# **These rules are also what makes the writeback order load-bearing.** Stage three re-lints
# after every single write and rolls back a write that fails, so an intermediate state has to
# lint clean. That constrains the order: the defect block cannot be appended before its item
# reaches `done-with-defect`, and a claim's `evidence` has to be written before its `disputed`
# label. `references/schema/execution-writeback.md` states the order these rules imply.

# Statuses whose whole meaning is that the item finished and produced something.
COMPLETED_STATUSES = {"done", "done-with-defect"}

# Statuses that end an item without completing it. Each is a claim about why, and R-6.1 asks
# for that claim in writing.
DIAGNOSED_STATUSES = {"failed", "stale", "blocked-by-failure"}

# What a defect's claim may be labelled. The asymmetry of R-7.2 against R-7.5 is the subtlest
# thing in stage three: a failing test of a cited or ratified claim is a defect in the code and
# is committed red, while a failing test of a pinned claim impeaches the planner and commits
# nothing. A defect registered against a pinned claim would block deploys over the planner's
# reading of the code, which is the fiction R-7.5 exists to prevent.
DEFECT_CLAIM_LABELS = {"cited", "ratified", "ratified-as-observed"}


def check_execution(by_kind, meta, items, item_blocks, claims, path, problems, phase, anchor):
    if phase not in POST_EXECUTION_PHASES:
        check_execution_absent(by_kind, meta, items, item_blocks, claims, path, problems, phase)
        check_closeout_absent(by_kind, path, problems, phase)
        return

    meta_node = meta.node if meta is not None else None
    meta_line = meta.fence_line if meta is not None else anchor

    if meta_node is not None and not meta_node.get("approved"):
        problems.append(
            Problem(
                "executed-without-approval",
                path,
                meta_line,
                "this plan has been executed and carries no `approved` field in `plan-meta`",
                "R-4.1: an unapproved plan is never executed. Either the owner approved it "
                "and the approval was never written down, or something ran a plan it should "
                "not have. Both are worth knowing which.",
            )
        )

    defects = check_defects(by_kind, items, claims, path, problems)
    logs = check_execution_logs(by_kind, items, path, problems)
    check_item_execution(items, item_blocks, defects, logs, path, problems)
    check_disputes(claims, by_kind, items, path, problems)
    check_run_summary(by_kind, items, claims, defects, path, problems, anchor)

    if phase == "closed":
        check_closeout(by_kind, items, claims, defects, path, problems, anchor)
    else:
        check_closeout_absent(by_kind, path, problems, phase)
        check_defects_unanswered(by_kind, defects, path, problems)


def check_execution_absent(by_kind, meta, items, item_blocks, claims, path, problems, phase):
    """Nothing stage three writes may appear in a plan stage three has not run.

    The same reasoning as `premature-status` and `premature-claim-label`, applied to the
    fields and blocks the writeback adds. A plan arriving with a defect registry is asserting
    that execution found something before execution happened.
    """
    for kind in sorted(planlib.EXECUTION_BLOCKS):
        for block in by_kind.get(kind, []):
            problems.append(
                Problem(
                    "premature-execution-block",
                    path,
                    block.fence_line,
                    f"a `{kind}` block appears in a plan at phase {phase!r}",
                    "The execution log, the defect registry, and the run summary are written "
                    "by stage three. Pass --phase executed when linting a plan it has "
                    "written back into.",
                )
            )

    for item_id, item in sorted(items.items(), key=lambda kv: item_sort_key(kv[0])):
        line = item_blocks[item_id].fence_line
        for field in ("actuals", "commit", "diagnosis"):
            if field in item:
                problems.append(
                    Problem(
                        "premature-execution-field",
                        path,
                        item.line_of(field, line),
                        f"{item_id} carries `{field}` in a plan at phase {phase!r}",
                        "R-2.1 lists the plan fields the executor writes, and this is one of "
                        "them. The planner writes none of them.",
                    )
                )

    for claim_id, claim in sorted(claims.items()):
        if "evidence" in claim:
            problems.append(
                Problem(
                    "premature-execution-field",
                    path,
                    claim.line_of("evidence", 1),
                    f"{claim_id} carries `evidence` in a plan at phase {phase!r}",
                    "`evidence` accompanies a `disputed` label, which only stage three "
                    "writes (R-7.5).",
                )
            )

    if phase == "planned" and meta is not None and meta.node.get("approved"):
        problems.append(
            Problem(
                "premature-approval",
                path,
                meta.node.line_of("approved", meta.fence_line),
                "a freshly written plan already carries its own approval",
                "Approval is the owner's act at the review sitting, like a resolution and a "
                "ratification. Pass --phase reviewed when linting after that sitting.",
            )
        )


def check_defects(by_kind, items, claims, path, problems):
    """R-7.2's registry: every entry resolves, and every red test was verified before it stood.

    Returns the defects by id, because two later rules need them: R-7.4's suspension rule
    reads which claims have a registry test, and the run summary must agree with the registry.
    """
    defects = {}
    for block in by_kind.get("defect", []):
        node = block.node
        line = block.fence_line
        defect_id = node.get("id")
        if not isinstance(defect_id, str):
            continue
        if defect_id in defects:
            problems.append(
                Problem("duplicate-id", path, line, f"defect {defect_id} is defined twice")
            )
            continue
        defects[defect_id] = node

        claim_id = node.get("claim")
        claim = claims.get(claim_id) if isinstance(claim_id, str) else None
        if isinstance(claim_id, str) and claim is None:
            problems.append(
                Problem(
                    "defect-dangling-claim",
                    path,
                    node.line_of("claim", line),
                    f"{defect_id} records a defect against claim {claim_id}, which no claim "
                    "block defines",
                )
            )
        elif claim is not None and claim.get("label") not in DEFECT_CLAIM_LABELS:
            problems.append(
                Problem(
                    "defect-claim-not-cited",
                    path,
                    node.line_of("claim", line),
                    f"{defect_id} registers a defect against {claim_id}, which is labelled "
                    f"{claim.get('label')!r}",
                    "R-7.2 and R-7.5 are asymmetric and this is the asymmetry. A defect "
                    "belongs to a claim carrying the requirements document's authority "
                    "(`cited`) or the owner's personally (`ratified`). A failing test of a "
                    "`pinned` claim impeaches the planner's reading instead: mark the claim "
                    "`disputed` with its evidence and commit nothing red.",
                )
            )

        item_id = node.get("item")
        item = items.get(item_id) if isinstance(item_id, str) else None
        if isinstance(item_id, str) and item is None:
            problems.append(
                Problem(
                    "defect-dangling-item",
                    path,
                    node.line_of("item", line),
                    f"{defect_id} names item {item_id}, which no work item defines",
                )
            )
        elif item is not None and item.get("status") != "done-with-defect":
            problems.append(
                Problem(
                    "defect-item-not-done-with-defect",
                    path,
                    node.line_of("item", line),
                    f"{defect_id} was surfaced by {item_id}, whose status is "
                    f"{item.get('status')!r}",
                    "R-7.2: the executor wrote the test the claim describes and the test "
                    "failed, so the item was done correctly and the code is what is wrong. "
                    "That is `done-with-defect`. Write the status before appending the "
                    "registry entry.",
                )
            )

        verification = node.get("verification")
        if isinstance(verification, dict):
            if verification.get("brief") != "faithfulness":
                problems.append(
                    Problem(
                        "defect-wrong-brief",
                        path,
                        node.line_of("verification", line),
                        f"{defect_id}'s verification records the "
                        f"{verification.get('brief')!r} brief",
                        "R-7.3 names one brief for this: `faithfulness`, given only the "
                        "claim's text and the test.",
                    )
                )
            if verification.get("verdict") != "faithful":
                problems.append(
                    Problem(
                        "defect-unverified",
                        path,
                        node.line_of("verification", line),
                        f"{defect_id} stands red with a verification verdict of "
                        f"{verification.get('verdict')!r}",
                        "R-7.3 is unconditional: a red test stands only once a fresh-context "
                        "verifier confirms it asserts the claim. A verdict of anything but "
                        "`faithful` means the test was the problem — fix it and retry, "
                        "rather than registering a defect over a misreading.",
                    )
                )

        test = node.get("test")
        if isinstance(test, dict):
            for field in ("file", "name"):
                value = test.get(field)
                if isinstance(value, str) and value.startswith(("/", "~")):
                    problems.append(
                        Problem(
                            "absolute-path",
                            path,
                            node.line_of("test", line),
                            f"{defect_id}'s test `{field}` is an absolute path {value!r}",
                        )
                    )
    return defects


def check_execution_logs(by_kind, items, path, problems):
    """Every attempt names an item that exists, and the attempts of one item are distinct.

    Returns {item_id: [attempt numbers]}, which `check_item_execution` uses to hold
    `actuals.attempts` to the number of attempts actually logged.
    """
    logs = {}
    for block in by_kind.get("execution-log", []):
        node = block.node
        line = block.fence_line
        item_id = node.get("item")
        if not isinstance(item_id, str):
            continue
        if item_id not in items:
            problems.append(
                Problem(
                    "log-dangling-item",
                    path,
                    node.line_of("item", line),
                    f"an execution log entry names item {item_id}, which no work item defines",
                )
            )
            continue
        attempt = node.get("attempt")
        if isinstance(attempt, int):
            if attempt in logs.get(item_id, []):
                problems.append(
                    Problem(
                        "duplicate-attempt",
                        path,
                        node.line_of("attempt", line),
                        f"{item_id} has two execution log entries for attempt {attempt}",
                        "One entry per attempt. Two entries wearing one number means one of "
                        "them is describing a different run.",
                    )
                )
            logs.setdefault(item_id, []).append(attempt)
    return logs


def check_item_execution(items, item_blocks, defects, logs, path, problems):
    """What each terminal status obliges the executor to have written down."""
    registry_claims = {
        node.get("claim") for node in defects.values() if isinstance(node.get("claim"), str)
    }

    for item_id, item in sorted(items.items(), key=lambda kv: item_sort_key(kv[0])):
        line = item_blocks[item_id].fence_line
        status = item.get("status")
        status_line = item.line_of("status", line)

        if status in COMPLETED_STATUSES:
            if not item.get("commit"):
                problems.append(
                    Problem(
                        "done-without-commit",
                        path,
                        status_line,
                        f"{item_id} is {status!r} and names no commit",
                        "R-5.3: one commit per completed item, so any failure leaves clean, "
                        "recoverable, attributable state. An item that completed without one "
                        "is not attributable to anything.",
                    )
                )
            if not item.get("actuals"):
                problems.append(
                    Problem(
                        "done-without-actuals",
                        path,
                        status_line,
                        f"{item_id} is {status!r} and records no actuals",
                        "R-9.1: files touched, check outcomes, and timings are recorded from "
                        "the repository rather than from self-report. Without them stage four "
                        "cannot diff the declared footprint against the actual one, which is "
                        "the measurement planning R-10.3 gates concurrent execution on.",
                    )
                )
            if item_id not in logs:
                problems.append(
                    Problem(
                        "missing-execution-log",
                        path,
                        status_line,
                        f"{item_id} is {status!r} and has no execution log entry",
                        "Every attempt is logged, including the one that worked first time.",
                    )
                )

        if status in DIAGNOSED_STATUSES and not item.get("diagnosis"):
            problems.append(
                Problem(
                    "undiagnosed-failure",
                    path,
                    status_line,
                    f"{item_id} is {status!r} and carries no diagnosis",
                    "R-6.1 for `failed`, R-4.3 for `stale`, R-6.2 for `blocked-by-failure`. "
                    "Each of these is a claim about why the item did not complete, and the "
                    "claim is only useful in writing: what was attempted, what the check "
                    "runner reported, and which dependency or target is responsible.",
                )
            )

        actuals = item.get("actuals")
        if not isinstance(actuals, dict):
            continue

        attempts = actuals.get("attempts")
        logged = len(logs.get(item_id, []))
        if isinstance(attempts, int) and logged and attempts != logged:
            problems.append(
                Problem(
                    "attempt-count-mismatch",
                    path,
                    actuals.line_of("attempts", status_line),
                    f"{item_id} records {attempts} attempt(s) and has {logged} execution log "
                    "entr(y/ies)",
                    "One of the two is missing a write. The log is the evidence; the count "
                    "is the summary of it.",
                )
            )

        check_recorded_checks(actuals, item_id, registry_claims, path, status_line, problems)
        check_footprint_accuracy(item, actuals, item_id, path, status_line, problems)


def check_recorded_checks(actuals, item_id, registry_claims, path, line, problems):
    """R-10.2 on every recorded outcome, and R-7.4 on the mutation ones."""
    checks = actuals.get("checks") or []
    checks_line = actuals.line_of("checks", line)
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            continue
        where = f"{item_id} recorded check {i + 1}"
        outcome = check.get("outcome")
        if outcome in ("failed", "suspended", "not-run") and not (check.get("detail") or "").strip():
            problems.append(
                Problem(
                    "check-outcome-unexplained",
                    path,
                    checks_line,
                    f"{where} is {outcome!r} with no `detail`",
                    "R-10.2: a check the runner could not run is reported as not-run and "
                    "never inferred, and a failure with no detail is a failure nobody can act "
                    "on. Say what happened.",
                )
            )
        if check.get("kind") != "mutation":
            continue
        claim_id = check.get("claim")
        if claim_id in registry_claims and outcome == "passed":
            problems.append(
                Problem(
                    "mutation-not-suspended",
                    path,
                    checks_line,
                    f"{where} records a mutation for {claim_id} as `passed`, and {claim_id} "
                    "has a test standing red in the defect registry",
                    "R-7.4: mutating code against an already-failing test proves nothing, so "
                    "the check is recorded `suspended` and activates when the test goes "
                    "green. Recording it as passed claims the suite can detect a defect it "
                    "has not been shown to detect.",
                )
            )


def check_footprint_accuracy(item, actuals, item_id, path, line, problems):
    """R-2.2: an item that touched a file nothing declared fails, rather than widening.

    The measurement this protects is planning R-10.3's, which gates concurrent execution on
    declared footprints matching actual ones. That measurement is worthless if the executor
    may widen a footprint to make it true, so the widening has to be a failure rather than an
    edit — and the edit is forbidden outright by R-2.1, which does not list `files-touched`
    among the fields the executor may write.
    """
    declared = footprint_of(item)
    actual = set()
    touched = actuals.get("files_touched") or {}
    for group in ("production", "test", "config"):
        for entry in touched.get(group) or []:
            if isinstance(entry, str):
                actual.add(entry)

    outside = sorted(actual - declared)
    if not outside:
        return
    problems.append(
        Problem(
            "footprint-exceeded",
            path,
            actuals.line_of("files_touched", line),
            f"{item_id} touched {len(outside)} file(s) outside its declared footprint: "
            + ", ".join(outside),
            "R-2.2: the executor does not improvise a footprint expansion. The item fails "
            "with an explanation of what was needed and why, and widening `files-touched` to "
            "match is forbidden — it is planner content, and rewriting it would destroy the "
            "one measurement that could justify running slices concurrently.",
        )
    )


def check_disputes(claims, by_kind, items, path, problems):
    """R-7.5: a dispute carries its evidence, and the item that raised it failed.

    A dispute is the one finding this stage produces that commits nothing. Its entire weight
    rests on the evidence pointer and on the item's status, so both are required rather than
    conventional.
    """
    blocks_by_id = {b.node.get("id"): b for b in by_kind.get("claim", [])}

    for claim_id, claim in sorted(claims.items()):
        if claim.get("label") != "disputed":
            continue
        line = blocks_by_id[claim_id].fence_line if claim_id in blocks_by_id else 1

        if not (claim.get("evidence") or "").strip():
            problems.append(
                Problem(
                    "disputed-without-evidence",
                    path,
                    claim.line_of("label", line),
                    f"{claim_id} is labelled `disputed` and carries no `evidence`",
                    "R-7.5: the executor captures the test as written and the observed "
                    "behavior, in the sidecar log or on a side branch, and names it here. A "
                    "dispute with no evidence is an unbacked assertion that the planner "
                    "misread the code, made by the party that would otherwise have to write "
                    "the test.",
                )
            )

        asserting = [
            item_id
            for item_id, item in items.items()
            if claim_id in (item.get("claims") or [])
        ]
        if asserting and not any(items[i].get("status") == "failed" for i in asserting):
            problems.append(
                Problem(
                    "dispute-item-not-failed",
                    path,
                    claim.line_of("label", line),
                    f"{claim_id} is `disputed` but none of the item(s) asserting it "
                    f"({', '.join(sorted(asserting, key=item_sort_key))}) is `failed`",
                    "R-7.5: a dispute fails the item. The claim was the specification the "
                    "item was written against, and it did not hold — so the item did not "
                    "deliver what it promised, however correct the executor's work was.",
                )
            )


def check_run_summary(by_kind, items, claims, defects, path, problems, anchor):
    """The summary is derived, so it must agree with what it was derived from.

    Stage four consumes this block without re-parsing the plan (R-9.3). A summary that has
    drifted from the statuses beneath it would be believed, and the drift is exactly what
    happens when a late status change lands after the summary is written.
    """
    blocks = by_kind.get("run-summary", [])
    if not blocks:
        return
    node = blocks[0].node
    line = blocks[0].fence_line

    actual_items = {}
    for item_id, item in items.items():
        status = item.get("status")
        if isinstance(status, str):
            actual_items.setdefault(status, set()).add(item_id)

    recorded_items = {}
    for entry in node.get("items") or []:
        if isinstance(entry, dict) and isinstance(entry.get("status"), str):
            recorded_items[entry["status"]] = {
                i for i in (entry.get("ids") or []) if isinstance(i, str)
            }
            if isinstance(entry.get("count"), int) and entry["count"] != len(
                recorded_items[entry["status"]]
            ):
                problems.append(
                    Problem(
                        "run-summary-count",
                        path,
                        node.line_of("items", line),
                        f"the run summary says {entry['count']} item(s) are "
                        f"{entry['status']!r} and lists {len(recorded_items[entry['status']])}",
                    )
                )

    for status in sorted(set(actual_items) | set(recorded_items)):
        if actual_items.get(status, set()) != recorded_items.get(status, set()):
            problems.append(
                Problem(
                    "run-summary-disagrees",
                    path,
                    node.line_of("items", line),
                    f"the run summary's {status!r} items are "
                    f"{sorted(recorded_items.get(status, set()), key=item_sort_key)} and the "
                    f"plan's are {sorted(actual_items.get(status, set()), key=item_sort_key)}",
                    "The summary is derived from the plan, not authored beside it. Re-run "
                    "run_summary.py and replace the block.",
                )
            )

    recorded_defects = {d for d in (node.get("defects") or []) if isinstance(d, str)}
    if recorded_defects != set(defects):
        problems.append(
            Problem(
                "run-summary-disagrees",
                path,
                node.line_of("defects", line),
                f"the run summary lists defects {sorted(recorded_defects)} and the registry "
                f"holds {sorted(defects)}",
            )
        )

    recorded_disputes = {d for d in (node.get("disputes") or []) if isinstance(d, str)}
    actual_disputes = {c for c, n in claims.items() if n.get("label") == "disputed"}
    if recorded_disputes != actual_disputes:
        problems.append(
            Problem(
                "run-summary-disagrees",
                path,
                node.line_of("disputes", line),
                f"the run summary lists disputes {sorted(recorded_disputes)} and the plan "
                f"marks {sorted(actual_disputes)} `disputed`",
            )
        )


# --------------------------------------------------------------------------------------
# The close-out phase
# --------------------------------------------------------------------------------------
#
# `--phase closed` is to stage four what `--phase executed` is to stage three: the phase that
# permits its writes is the phase that insists it made all of them. A closed plan whose defect
# registry still carries a null `resolution` is a run that was declared finished with decision
# debt in it, which is precisely what R-6.1 exists to make impossible.
#
# **The rules are lopsided on purpose.** `downgrade` — applying a known-failure marker so the
# suite reports green over a defect that is still real — carries the strictest record of the
# four, because it is the only option no agent may reach and the only one whose effect is that
# the failure stops being visible. Everything else about the close-out is symmetric; this is
# not, and the asymmetry is the point.

# What each option leaves the defect's test in, and whether it produces a commit. The two
# `standing` options apply nothing, so a commit against them is a transformation somebody made
# that no decision authorized.
_OPTION_EXPECTATIONS = {
    "fix-the-code": ("standing", False),
    "accept-with-red": ("standing", False),
    "requirement-wrong": ("rewritten", True),
    "downgrade": ("marked", True),
}


def check_closeout_absent(by_kind, path, problems, phase):
    """Nothing stage four writes may appear in a plan stage four has not closed.

    The exact mirror of `premature-execution-block`, one phase later. A plan arriving with a
    close-out record is asserting the owner answered a defect at a gate that has not been held.
    """
    for kind in sorted(planlib.CLOSEOUT_BLOCKS):
        for block in by_kind.get(kind, []):
            problems.append(
                Problem(
                    "premature-closeout-block",
                    path,
                    block.fence_line,
                    f"a `{kind}` block appears in a plan at phase {phase!r}",
                    "The close-out records, the dispute decisions, the pipeline findings, and "
                    "the run record are written by stage four at the close-out gate. Pass "
                    "--phase closed when linting a plan it has closed.",
                )
            )


def check_defects_unanswered(by_kind, defects, path, problems):
    """At the executed phase a defect's `resolution` must still be null.

    The mirror image of the rule below, and the one that matters more: an executor that fills
    in a resolution has answered its own finding, which is the failure R-2.5 of the execution
    document and R-6.1 of this one are jointly written to prevent. The registry entry is a
    question put to the owner, and a question that arrives with an answer already in it was
    never put to anybody.
    """
    blocks = {b.node.get("id"): b for b in by_kind.get("defect", [])}
    for defect_id, node in sorted(defects.items()):
        if node.get("resolution") is None:
            continue
        line = blocks[defect_id].fence_line if defect_id in blocks else 1
        problems.append(
            Problem(
                "defect-answered-before-closeout",
                path,
                node.line_of("resolution", line),
                f"{defect_id} carries a resolution of {node.get('resolution')!r} in a plan at "
                "phase 'executed'",
                "R-7.6 of the execution document reserves this field to the owner at stage "
                "four's close-out gate. If the gate has been held, lint with --phase closed; "
                "if it has not, this answer was written by something that was not authorized "
                "to give it.",
            )
        )


def check_closeout(by_kind, items, claims, defects, path, problems, anchor):
    """Every defect answered, every answer applied, and the record agreeing with both."""
    closeouts, by_defect = collect_closeouts(by_kind, defects, path, problems)
    check_defect_answers(by_kind, defects, by_defect, path, problems)

    for closeout_id in sorted(closeouts):
        block = closeouts[closeout_id]
        check_one_closeout(block, defects, claims, path, problems)

    check_relabelled_claims(by_kind, claims, defects, by_defect, path, problems)
    decisions = check_dispute_decisions(by_kind, claims, path, problems)
    findings = check_pipeline_findings(by_kind, path, problems)
    check_run_record(
        by_kind, items, claims, defects, closeouts, decisions, findings, path, problems, anchor
    )


def collect_closeouts(by_kind, defects, path, problems):
    """The close-out blocks by id, and by the defect each answers.

    Two blocks answering one defect is the failure worth naming: it is what happens when the
    gate is re-run and the owner changes their mind, and leaving both in place would make the
    record say two different things about the same decision.
    """
    closeouts = {}
    by_defect = {}
    for block in by_kind.get("close-out", []):
        node = block.node
        line = block.fence_line
        closeout_id = node.get("id")
        if not isinstance(closeout_id, str):
            continue
        if closeout_id in closeouts:
            problems.append(
                Problem("duplicate-id", path, line, f"close-out {closeout_id} is defined twice")
            )
            continue
        closeouts[closeout_id] = block

        defect_id = node.get("defect")
        if not isinstance(defect_id, str):
            continue
        if defect_id not in defects:
            problems.append(
                Problem(
                    "closeout-dangling-defect",
                    path,
                    node.line_of("defect", line),
                    f"{closeout_id} answers defect {defect_id}, which the registry does not "
                    "define",
                    "A close-out answers a defect stage three registered. If the defect is "
                    "real, its registry entry is missing; if it is not, this decision is "
                    "about nothing.",
                )
            )
            continue
        if defect_id in by_defect:
            problems.append(
                Problem(
                    "duplicate-closeout",
                    path,
                    node.line_of("defect", line),
                    f"{defect_id} is answered twice: by "
                    f"{by_defect[defect_id].node.get('id')} and by {closeout_id}",
                    "One decision per defect. Two records mean the gate was held twice and "
                    "the superseded answer was left in place, so the plan now says two "
                    "different things about one defect. Delete the one that was not taken.",
                )
            )
            continue
        by_defect[defect_id] = block
    return closeouts, by_defect


def check_defect_answers(by_kind, defects, by_defect, path, problems):
    """R-6.1: every registry entry carries the owner's answer, and the answer has a record."""
    blocks = {b.node.get("id"): b for b in by_kind.get("defect", [])}
    for defect_id, node in sorted(defects.items()):
        line = blocks[defect_id].fence_line if defect_id in blocks else 1
        resolution = node.get("resolution")

        if resolution is None:
            problems.append(
                Problem(
                    "defect-unresolved",
                    path,
                    node.line_of("resolution", line),
                    f"{defect_id} has no `resolution` in a closed plan",
                    "R-6.1: the run is not closed until every registry entry carries the "
                    "owner's answer. This is the whole reason stage four has a gate rather "
                    "than only a report — a defect with no decision rides into the default "
                    "branch as debt nobody agreed to take on.",
                )
            )
            continue

        block = by_defect.get(defect_id)
        if block is None:
            problems.append(
                Problem(
                    "defect-without-closeout",
                    path,
                    node.line_of("resolution", line),
                    f"{defect_id} is resolved {resolution!r} and no `close-out` block records "
                    "the decision",
                    "The resolution field says which answer; the close-out block says who "
                    "decided, when, why, what was applied, and what the check runner made of "
                    "it. Neither is optional and neither substitutes for the other.",
                )
            )
            continue

        option = block.node.get("option")
        if isinstance(option, str) and option != resolution:
            problems.append(
                Problem(
                    "closeout-option-mismatch",
                    path,
                    block.node.line_of("option", block.fence_line),
                    f"{defect_id}'s registry entry is resolved {resolution!r} and its "
                    f"close-out record chooses {option!r}",
                    "The two are one fact written in two places. Whichever is wrong, a reader "
                    "cannot tell which, so both have to be corrected together.",
                )
            )


def check_one_closeout(block, defects, claims, path, problems):
    """Everything one close-out record owes, which depends on which option it took."""
    node = block.node
    line = block.fence_line
    closeout_id = node.get("id")
    option = node.get("option")
    if option not in _OPTION_EXPECTATIONS:
        return  # the schema already reported the bad or missing option

    expected_state, expects_commit = _OPTION_EXPECTATIONS[option]

    state = node.get("red-test-state")
    if isinstance(state, str) and state != expected_state:
        problems.append(
            Problem(
                "red-test-state-mismatch",
                path,
                node.line_of("red-test-state", line),
                f"{closeout_id} chose {option!r} and records the defect's test as {state!r}",
                f"{option!r} leaves the test {expected_state!r}. The two options that apply "
                "nothing leave the red standing as the ready-made verification; "
                "`requirement-wrong` rewrites it to assert the observed behavior; `downgrade` "
                "marks it as a known failure. A record that disagrees with its own option "
                "describes a transformation nobody chose.",
            )
        )

    commit = node.get("commit")
    if expects_commit and not commit:
        problems.append(
            Problem(
                "consequence-without-commit",
                path,
                node.line_of("commit", line),
                f"{closeout_id} chose {option!r} and names no commit",
                "R-6.2: consequences are applied, not deferred, and one commit per decision is "
                "what makes the branch presented for merge the branch the owner's decisions "
                "produced. An applied transformation with no commit is either uncommitted work "
                "or work that never happened.",
            )
        )
    if not expects_commit and commit:
        problems.append(
            Problem(
                "noop-option-with-commit",
                path,
                node.line_of("commit", line),
                f"{closeout_id} chose {option!r} and names commit {commit!r}",
                "Neither `fix-the-code` nor `accept-with-red` applies anything: the defect is "
                "real, the red test stands, and the difference between them is only who "
                "enforces it. A commit against one of them is an edit no decision authorized.",
            )
        )

    flag = node.get("amendment-flag")
    if option == "requirement-wrong" and not isinstance(flag, dict):
        problems.append(
            Problem(
                "requirement-wrong-without-amendment-flag",
                path,
                node.line_of("option", line),
                f"{closeout_id} chose `requirement-wrong` and emits no `amendment-flag`",
                "R-6.4: accepting the observed behavior means the document that specified "
                "something else is now known to be wrong. That is a defect in the document, "
                "tracked in the run ledger like any other finding until it is amended or "
                "contested. Without the flag the run silently ratifies a document it just "
                "contradicted.",
            )
        )
    if option != "requirement-wrong" and isinstance(flag, dict):
        problems.append(
            Problem(
                "amendment-flag-not-permitted",
                path,
                node.line_of("amendment-flag", line),
                f"{closeout_id} chose {option!r} and carries an `amendment-flag`",
                "Only `requirement-wrong` accepts observed behavior over a document. The other "
                "three leave the document standing and the defect real, so there is nothing to "
                "amend.",
            )
        )

    marker = node.get("marker")
    if option == "downgrade":
        if not isinstance(marker, dict):
            problems.append(
                Problem(
                    "downgrade-without-marker",
                    path,
                    node.line_of("option", line),
                    f"{closeout_id} chose `downgrade` and does not say where the marker went",
                    "This is the one option that makes a real failure stop being visible, and "
                    "it is the one option no agent may reach. The marker's file and exact form "
                    "are required so that anyone reading a green suite can find the reason it "
                    "is green and the decision that made it so.",
                )
            )
        elif isinstance(marker.get("form"), str) and node.get("defect") not in marker["form"]:
            problems.append(
                Problem(
                    "downgrade-marker-untraceable",
                    path,
                    node.line_of("marker", line),
                    f"{closeout_id}'s marker does not name {node.get('defect')}",
                    "The marker is the only thing left in the code once the suite goes green. "
                    "It must name the defect, so a reader who finds it can reach the decision, "
                    "the rationale, and the person who took it.",
                )
            )
        if isinstance(node.get("decided-by"), str) and _looks_automated(node["decided-by"]):
            problems.append(
                Problem(
                    "downgrade-decided-by-agent",
                    path,
                    node.line_of("decided-by", line),
                    f"{closeout_id} downgrades {node.get('defect')} and names "
                    f"{node['decided-by']!r} as the decider",
                    "R-6.2 and execution R-2.5: downgrading is available only as the owner's "
                    "recorded decision. A cited claim carries a requirements document's "
                    "authority and a ratified claim carries the owner's personally, and the "
                    "authority to declare either non-blocking belongs to whoever made it "
                    "binding. Name that person.",
                )
            )
    elif isinstance(marker, dict):
        problems.append(
            Problem(
                "marker-not-permitted",
                path,
                node.line_of("marker", line),
                f"{closeout_id} chose {option!r} and records a known-failure marker",
                "Only `downgrade` applies one. If a marker really was applied under a "
                "different answer, the answer is `downgrade` and it was recorded wrongly.",
            )
        )

    if option == "requirement-wrong":
        defect = defects.get(node.get("defect"))
        claim_id = defect.get("claim") if isinstance(defect, dict) else None
        claim = claims.get(claim_id) if isinstance(claim_id, str) else None
        if claim is not None and claim.get("label") != "ratified-as-observed":
            problems.append(
                Problem(
                    "requirement-wrong-claim-not-relabelled",
                    path,
                    node.line_of("option", line),
                    f"{closeout_id} chose `requirement-wrong` and {claim_id} is still "
                    f"labelled {claim.get('label')!r}",
                    "R-6.2's transformation has three parts and this is the one with no "
                    "visible effect on the branch, which is why it is the one that gets "
                    "forgotten. The claim now records observed behavior rather than specified "
                    "behavior, and the report's accounting splits by exactly that distinction.",
                )
            )

    check_closeout_verification(node, closeout_id, path, line, problems)


def _looks_automated(name):
    """Whether a decider's name is an agent rather than a person.

    Deliberately crude and deliberately narrow. It catches the specific thing worth catching —
    a downgrade recorded with the tooling's own name in the decider field — and it will not
    catch a determined evasion. It is not meant to: the rule that matters is that a human name
    sits beside the decision, and a false name is a different kind of problem from a missing
    one.
    """
    lowered = name.strip().lower()
    return lowered in {
        "claude", "agent", "assistant", "automation", "automated", "bot", "ci",
        "close-out executor", "closeout", "executor", "stage four", "test-reporting",
        "the skill", "tooling", "unknown", "n/a", "none",
    }


def check_closeout_verification(node, closeout_id, path, line, problems):
    """R-6.2: the check runner verified the consequence before the gate advanced."""
    checks = node.get("checks") or []
    checks_line = node.line_of("checks", line)
    passed = 0
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            continue
        outcome = check.get("outcome")
        if outcome == "passed":
            passed += 1
        if outcome in ("failed", "suspended", "not-run") and not (check.get("detail") or "").strip():
            problems.append(
                Problem(
                    "closeout-check-unexplained",
                    path,
                    checks_line,
                    f"{closeout_id} recorded check {i + 1} is {outcome!r} with no `detail`",
                    "The same standard the execution checks are held to: an outcome with no "
                    "detail is indistinguishable from a guess.",
                )
            )
        if outcome == "failed":
            problems.append(
                Problem(
                    "closeout-check-failed",
                    path,
                    checks_line,
                    f"{closeout_id} recorded a failed check and the gate advanced anyway",
                    "R-6.2 verifies each consequence before the gate advances. A decision "
                    "whose transformation did not verify has not been applied, whatever the "
                    "commit says — reopen it rather than closing over it.",
                )
            )
    if checks and not passed:
        problems.append(
            Problem(
                "closeout-unverified",
                path,
                checks_line,
                f"{closeout_id} records {len(checks)} check(s) and none of them passed",
                "Something has to have confirmed the branch is in the state the decision "
                "describes. A close-out whose every check was skipped or unrunnable is a "
                "decision recorded rather than a decision applied.",
            )
        )

    for field, value in (
        ("marker", (node.get("marker") or {}).get("file")),
        ("amendment-flag", (node.get("amendment-flag") or {}).get("document")),
    ):
        if isinstance(value, str) and value.startswith(("/", "~")):
            problems.append(
                Problem(
                    "absolute-path",
                    path,
                    node.line_of(field, line),
                    f"{closeout_id}'s `{field}` names the absolute path {value!r}",
                    "Repository-relative paths only, so the record is usable from any "
                    "checkout.",
                )
            )


def check_relabelled_claims(by_kind, claims, defects, by_defect, path, problems):
    """The mirror of `requirement-wrong-claim-not-relabelled`, from the claim's side.

    Both directions are needed and neither implies the other. A `requirement-wrong` decision
    with an un-relabelled claim overstates what the suite asserts; a claim relabelled with no
    decision behind it is a downgrade of a cited claim's authority that nobody recorded — which
    is the same act stage three is forbidden from taking, arriving one stage later.
    """
    blocks = {b.node.get("id"): b for b in by_kind.get("claim", [])}
    justified = set()
    for defect_id, block in by_defect.items():
        if block.node.get("option") != "requirement-wrong":
            continue
        defect = defects.get(defect_id)
        claim_id = defect.get("claim") if isinstance(defect, dict) else None
        if isinstance(claim_id, str):
            justified.add(claim_id)

    for claim_id, claim in sorted(claims.items()):
        if claim.get("label") != "ratified-as-observed" or claim_id in justified:
            continue
        line = blocks[claim_id].fence_line if claim_id in blocks else 1
        problems.append(
            Problem(
                "relabelled-without-closeout",
                path,
                claim.line_of("label", line),
                f"{claim_id} is labelled `ratified-as-observed` and no `requirement-wrong` "
                "close-out accounts for it",
                "This label means the owner examined a specific failing test, ruled the claim "
                "wrong, and accepted what the code does instead. It is reachable only through "
                "that decision. Applied without one, it quietly converts a specified behavior "
                "into an observed one — which is the precise distinction the report's "
                "asserted-behavior accounting is built on.",
            )
        )


def check_dispute_decisions(by_kind, claims, path, problems):
    """R-6.5: optional and non-blocking, but an answer that exists must be about something.

    Nothing here requires a dispute to be decided. A dispute is a planner error with evidence
    captured and nothing red on the branch, so leaving it open is a legitimate outcome — it
    stays an open ledger item and feeds the planner-accuracy finding. What is checked is that a
    decision names a claim that really is disputed and carries what its option needs.
    """
    decisions = {}
    for block in by_kind.get("dispute-decision", []):
        node = block.node
        line = block.fence_line
        claim_id = node.get("claim")
        if not isinstance(claim_id, str):
            continue
        if claim_id in decisions:
            problems.append(
                Problem(
                    "duplicate-dispute-decision",
                    path,
                    node.line_of("claim", line),
                    f"{claim_id} carries two dispute decisions",
                )
            )
            continue
        decisions[claim_id] = node

        claim = claims.get(claim_id)
        if claim is None:
            problems.append(
                Problem(
                    "dispute-decision-dangling-claim",
                    path,
                    node.line_of("claim", line),
                    f"a dispute decision names {claim_id}, which no claim block defines",
                )
            )
        elif claim.get("label") != "disputed":
            problems.append(
                Problem(
                    "dispute-decision-not-disputed",
                    path,
                    node.line_of("claim", line),
                    f"a dispute decision names {claim_id}, which is labelled "
                    f"{claim.get('label')!r} rather than `disputed`",
                    "R-6.5 presents impeached pinned claims at the gate. A decision about a "
                    "claim that was never impeached is answering a question nobody asked.",
                )
            )

        if node.get("option") == "correct-the-claim" and not (
            node.get("corrected-text") or ""
        ).strip():
            problems.append(
                Problem(
                    "correction-without-text",
                    path,
                    node.line_of("option", line),
                    f"{claim_id}'s dispute decision is `correct-the-claim` and carries no "
                    "`corrected-text`",
                    "The whole value of this answer is that the next round of planning starts "
                    "from a corrected claim rather than rediscovering the same misreading. "
                    "Without the text it is `leave-disputed` with a more optimistic name.",
                )
            )
    return decisions


def check_pipeline_findings(by_kind, path, problems):
    """R-8.2: stable identifiers, and a state that means what it says."""
    findings = {}
    for block in by_kind.get("pipeline-finding", []):
        node = block.node
        line = block.fence_line
        finding_id = node.get("id")
        if not isinstance(finding_id, str):
            continue
        if finding_id in findings:
            problems.append(
                Problem(
                    "duplicate-id", path, line, f"pipeline finding {finding_id} is defined twice"
                )
            )
            continue
        findings[finding_id] = node

        state = node.get("state")
        if state == "retired" and not (node.get("retired-by") or "").strip():
            problems.append(
                Problem(
                    "finding-retired-without-change",
                    path,
                    node.line_of("state", line),
                    f"{finding_id} is `retired` and names nothing that retired it",
                    "R-7.5: a finding is retired only explicitly, with the change that "
                    "addressed it named. A finding that goes quiet because nobody looked is "
                    "still open, and this project's own amendment workflow is the intended "
                    "consumer of the difference.",
                )
            )
        occurrences = node.get("occurrences")
        if state == "recurring" and isinstance(occurrences, int) and occurrences < 2:
            problems.append(
                Problem(
                    "finding-recurring-once",
                    path,
                    node.line_of("state", line),
                    f"{finding_id} is `recurring` and records {occurrences} occurrence(s)",
                    "R-8.2 flags a finding that recurs across runs without being retired or "
                    "contested. One occurrence is `open`.",
                )
            )
    return findings


def check_run_record(
    by_kind, items, claims, defects, closeouts, dispute_decisions, findings,
    path, problems, anchor,
):
    """The run record is derived, so it must agree with everything it was derived from.

    The same rule as the run summary's, one stage later and with more riding on it: the report
    states no figure that is not in this record, so a record that has drifted misreports the run
    with the tracer certifying every number in it.
    """
    blocks = by_kind.get("run-record", [])
    if not blocks:
        problems.append(
            Problem(
                "run-record-missing",
                path,
                anchor,
                "this plan is being linted as closed and carries no `run-record` block",
                "R-5.1: the run record is the single source for every figure the narrative "
                "report states, and R-6.1 makes the run closed only once the gate is complete. "
                "Run `run_record.py --write` before linting at this phase.",
            )
        )
        return
    node = blocks[0].node
    line = blocks[0].fence_line

    def disagree(field, recorded, actual, hint=None):
        problems.append(
            Problem(
                "run-record-disagrees",
                path,
                node.line_of(field, line),
                f"the run record's `{field}` is {sorted(recorded)} and the plan's is "
                f"{sorted(actual)}",
                hint or "The record is derived from the plan, not authored beside it. Re-run "
                        "run_record.py and replace the block.",
            )
        )

    recorded_items = {}
    for entry in node.get("items") or []:
        if isinstance(entry, dict) and isinstance(entry.get("status"), str):
            recorded_items[entry["status"]] = {
                i for i in (entry.get("ids") or []) if isinstance(i, str)
            }
    actual_items = {}
    for item_id, item in items.items():
        status = item.get("status")
        if isinstance(status, str):
            actual_items.setdefault(status, set()).add(item_id)
    for status in sorted(set(actual_items) | set(recorded_items)):
        if actual_items.get(status, set()) != recorded_items.get(status, set()):
            disagree(
                "items",
                recorded_items.get(status, set()),
                actual_items.get(status, set()),
                f"The disagreement is about the {status!r} items.",
            )

    # The claim labels are the one section the run record recomputes rather than copying
    # forward from the run summary, because the close-out gate changes them: a
    # `requirement-wrong` decision relabels a claim `ratified-as-observed`. So they are checked
    # against the plan here, where the run summary's are not.
    recorded_labels = {}
    for entry in node.get("claims") or []:
        if isinstance(entry, dict) and isinstance(entry.get("label"), str):
            recorded_labels[entry["label"]] = {
                c for c in (entry.get("ids") or []) if isinstance(c, str)
            }
    actual_labels = {}
    for claim_id, claim in claims.items():
        label = claim.get("label")
        if isinstance(label, str):
            actual_labels.setdefault(label, set()).add(claim_id)
    for label in sorted(set(actual_labels) | set(recorded_labels)):
        if actual_labels.get(label, set()) != recorded_labels.get(label, set()):
            disagree(
                "claims",
                recorded_labels.get(label, set()),
                actual_labels.get(label, set()),
                f"The disagreement is about the {label!r} claims. The record restates the "
                "labels as the plan holds them after close-out, so a mismatch means either a "
                "relabelling the record never saw or a record written before the gate.",
            )

    recorded_defects = {d for d in (node.get("defects") or []) if isinstance(d, str)}
    if recorded_defects != set(defects):
        disagree("defects", recorded_defects, set(defects))

    recorded_disputes = {d for d in (node.get("disputes") or []) if isinstance(d, str)}
    actual_disputes = {c for c, n in claims.items() if n.get("label") == "disputed"}
    if recorded_disputes != actual_disputes:
        disagree("disputes", recorded_disputes, actual_disputes)

    recorded_decisions = {}
    for entry in node.get("decisions") or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            recorded_decisions[entry["id"]] = (entry.get("defect"), entry.get("option"))
    actual_decisions = {
        closeout_id: (block.node.get("defect"), block.node.get("option"))
        for closeout_id, block in closeouts.items()
    }
    if set(recorded_decisions) != set(actual_decisions):
        disagree(
            "decisions",
            set(recorded_decisions),
            set(actual_decisions),
            "Every close-out block is a decision and every decision has a block. A record "
            "listing one the plan does not hold, or omitting one it does, is the shape a late "
            "change to the gate takes.",
        )
    else:
        for closeout_id in sorted(actual_decisions):
            if recorded_decisions[closeout_id] != actual_decisions[closeout_id]:
                problems.append(
                    Problem(
                        "run-record-disagrees",
                        path,
                        node.line_of("decisions", line),
                        f"the run record says {closeout_id} answered "
                        f"{recorded_decisions[closeout_id][0]} with "
                        f"{recorded_decisions[closeout_id][1]!r}, and the close-out block says "
                        f"{actual_decisions[closeout_id][0]} with "
                        f"{actual_decisions[closeout_id][1]!r}",
                    )
                )

    recorded_dispute_decisions = {
        entry.get("claim")
        for entry in (node.get("dispute_decisions") or [])
        if isinstance(entry, dict)
    }
    if recorded_dispute_decisions != set(dispute_decisions):
        disagree(
            "dispute_decisions", recorded_dispute_decisions, set(dispute_decisions)
        )

    recorded_findings = {
        entry.get("id") for entry in (node.get("findings") or []) if isinstance(entry, dict)
    }
    if recorded_findings != set(findings):
        disagree(
            "findings",
            recorded_findings,
            set(findings),
            "R-8.2: findings live in the ledger and are retired only explicitly. A record and "
            "a set of blocks that disagree about which exist is a finding about to be lost "
            "between the plan and the ledger.",
        )

    recorded_flags = {
        entry.get("id")
        for entry in (node.get("amendment_flags") or [])
        if isinstance(entry, dict)
    }
    actual_flags = {
        (block.node.get("amendment-flag") or {}).get("id")
        for block in closeouts.values()
        if isinstance(block.node.get("amendment-flag"), dict)
    }
    if recorded_flags != actual_flags:
        disagree("amendment_flags", recorded_flags, actual_flags)

    suite = node.get("final_suite")
    if isinstance(suite, dict):
        failed = suite.get("failed")
        expected = suite.get("expected_failures") or []
        if isinstance(failed, int) and failed and not expected:
            problems.append(
                Problem(
                    "final-suite-unexplained-red",
                    path,
                    node.line_of("final_suite", line),
                    f"the final suite reports {failed} failing test(s) and lists none of them "
                    "as expected",
                    "R-5.6 and R-9.2: a red suite at close-out is either the deliberate "
                    "consequence of a `fix-the-code` or `accept-with-red` decision, in which "
                    "case each red test is named here, or it is an unexplained failure the "
                    "report must not present as settled. Name them or explain them.",
                )
            )
        if suite.get("measured") is False and isinstance(failed, int):
            problems.append(
                Problem(
                    "final-suite-unmeasured-figures",
                    path,
                    node.line_of("final_suite", line),
                    "the final suite is recorded as not measured and still carries counts",
                    "R-9.2: a figure that was not measured is reported absent, never "
                    "estimated. Set `passed` and `failed` to null and say why in `note`.",
                )
            )


def check_waves(by_kind, slices, items, path, problems, anchor=1):
    computed = compute_waves(slices, items)
    blocks = by_kind.get("wave-schedule", [])
    if not blocks:
        problems.append(
            Problem(
                "no-wave-schedule",
                path,
                anchor,
                "the plan records no wave schedule",
                "R-10.2: the schedule is recorded as information, not instruction. Run "
                "`plan_lint.py --waves` and paste the result.",
            )
        )
        return computed

    node = blocks[0].node
    line = blocks[0].fence_line
    recorded = []
    for entry in node.get("waves") or []:
        if isinstance(entry, dict):
            recorded.append(sorted(entry.get("slices") or [], key=slice_sort_key))

    expected = [sorted(w["slices"], key=slice_sort_key) for w in computed]
    if recorded != expected:
        problems.append(
            Problem(
                "wave-mismatch",
                path,
                line,
                "the recorded wave schedule does not match the one computed from the "
                f"footprints and dependencies. recorded={recorded} computed={expected}",
                "Run `plan_lint.py <plan> --waves` and replace the block. The schedule is "
                "derived, not authored.",
            )
        )
    return computed


def check_coverage_of_findings(index, meta, by_kind, items, path, problems, meta_line=0):
    """R-11.3: every finding above the value line is covered by an item or excluded.

    This is the linter's most important rule. It is the only thing standing between a plan
    and a top-tier finding that quietly went missing.
    """
    if meta is None:
        return
    value_line = (meta.get("value_line") or {}).get("lowest_tier_planned")
    if value_line not in TIER_ORDER:
        return
    cutoff = TIER_ORDER.index(value_line)

    above = {
        finding["id"]: finding
        for finding in index.get("findings", [])
        if isinstance(finding, dict)
        and finding.get("tier") in TIER_ORDER
        and TIER_ORDER.index(finding["tier"]) <= cutoff
    }

    # Handled: the plan does something about it, or says in an audited place why it does not.
    # A work item plans it, an exclusion declines it with a reason the owner reads, an
    # escalation or decision routes it to the owner, a flagged note records that there is no
    # code to test.
    handled = set()
    for item in items.values():
        handled |= {r for r in (item.get("assessment-ref") or []) if isinstance(r, str)}
    for kind in ("exclusion", "escalation", "decision", "flagged"):
        for block in by_kind.get(kind, []):
            handled |= {r for r in (block.node.get("assessment-ref") or []) if isinstance(r, str)}

    # Deferred: the plan moved it to the backlog, which is not the same act.
    deferred = {}
    for block in by_kind.get("backlog-item", []):
        for ref in block.node.get("assessment-ref") or []:
            if isinstance(ref, str):
                deferred.setdefault(ref, []).append(block.node.get("id", "?"))

    for finding_id, finding in sorted(above.items()):
        if finding_id in handled:
            continue
        if finding_id in deferred:
            # **The hole this closes.** A backlog entry used to satisfy this rule, so a plan
            # could discharge every finding above its own value line by listing them as future
            # work and still lint clean. One real plan deferred two thirds of a repository that
            # way. The backlog is for work the charter forbids or a blocker prevents; declining
            # work that is merely larger is a decision, and a decision belongs in an exclusion,
            # where it carries a reason and a source and the owner reads it at the gate.
            problems.append(
                Problem(
                    "finding-only-backlogged",
                    path,
                    meta.line_of("value_line", meta_line),
                    f"assessment finding {finding_id} is in the `{finding['tier']}` tier, "
                    f"above this plan's value line of `{value_line}`, and the only thing "
                    f"referencing it is backlog entry {', '.join(deferred[finding_id])}",
                    "The backlog does not discharge a finding above the value line. Either "
                    "plan for it, or write an `exclusion` saying why this plan declines it — "
                    "an exclusion carries a reason and a source and the owner reads it, and a "
                    "backlog entry is read as work somebody might do later. If the honest "
                    "answer is that it did not fit, say that in an exclusion and keep the "
                    "backlog entry beside it. The finding is: "
                    f"{finding.get('title', '')[:140]}",
                )
            )
            continue
        problems.append(
            Problem(
                "uncovered-finding",
                path,
                meta.line_of("value_line", meta_line),
                f"assessment finding {finding_id} is in the `{finding['tier']}` tier, "
                f"which is above this plan's value line of `{value_line}`, and no work "
                "item, exclusion, escalation, decision, or flagged note references it",
                f"Either plan for it or exclude it with a reason. The finding is: "
                f"{finding.get('title', '')[:140]}",
            )
        )


# Categories that no plan can ever reach. Everything else is available to be planned for:
# `testable-as-is` today, `export-only` after a change that cannot alter behavior, and
# `needs-seam` after a seam the assessment already recommended.
UNREACHABLE_CATEGORIES = {"excluded", "integration-only"}


def compute_scope(index, claims, items):
    """How many classified functions this plan's claims actually locate on, and how many exist.

    Returns (planned, available, planned_entries). Both figures are derived from the
    assessment's testability data and the plan's own claim locations, using the same
    resolution the claim-enablement rule uses — so a claim that cannot be located is not
    counted, which is the right answer and the same one R-11.4 gives.
    """
    by_file = index_testability(index)
    entries = [
        entry
        for entries_for_file in by_file.values()
        for entry in entries_for_file
        if entry.get("category") not in UNREACHABLE_CATEGORIES
    ]

    def key(entry):
        return (entry.get("file"), entry.get("function"), entry.get("line"))

    available = {key(entry) for entry in entries}

    asserted = set()
    for item in items.values():
        for field in ("claims", "claims-enabled"):
            asserted |= {c for c in (item.get(field) or []) if isinstance(c, str)}

    planned = set()
    for claim_id in asserted:
        claim = claims.get(claim_id)
        if claim is None:
            continue
        for location in claim.get("locations") or []:
            for entry in candidates_for(by_file, location)[0]:
                if key(entry) in available:
                    planned.add(key(entry))

    return len(planned), len(available), planned


def check_scope(index, meta, claims, items, path, problems, meta_line=0):
    """The plan states how much of the reachable code it plans for, and the figure is true.

    **This is the rule that pushes back from below.** Every other completeness rule pushes
    from above — every finding above the value line must be handled, the claim budget caps a
    plan that is too large. Nothing noticed a plan that was too small, and a plan can sit above
    the value line on every finding while touching a third of the repository, because the value
    line bounds findings rather than code.

    Both figures are recomputed here rather than trusted, exactly as the wave schedule is. The
    planner cannot write a flattering number; what it must do is look at the true one and
    justify it, in a place the owner reads.
    """
    if meta is None or not index.get("testability"):
        return

    scope = meta.get("scope")
    if not isinstance(scope, dict):
        return  # the schema already reported it missing

    planned, available, _ = compute_scope(index, claims, items)
    line = meta.line_of("scope", meta_line)

    for field, computed in (("functions_planned", planned),
                            ("functions_available", available)):
        recorded = scope.get(field)
        if isinstance(recorded, int) and recorded != computed:
            problems.append(
                Problem(
                    "scope-mismatch",
                    path,
                    line,
                    f"`scope.{field}` records {recorded} and the plan's own claims against the "
                    f"assessment's testability data give {computed}",
                    "Run `plan_lint.py <plan> --scope` and paste the figures. They are derived "
                    "from the claim locations, not authored beside them.",
                )
            )

    if not available:
        return

    share = planned / available
    rationale = (scope.get("rationale") or "").strip()
    if share < 0.5 and len(rationale) < 200:
        problems.append(
            Problem(
                "narrow-scope-unexplained",
                path,
                line,
                f"this plan reaches {planned} of {available} reachable classified function(s) "
                f"— {share:.0%} — and its scope rationale is {len(rationale)} characters",
                "A plan that leaves more than half the reachable code unplanned is making a "
                "large decision, and the bar for explaining it rises with the share. Say what "
                "the rest is, what it would cost, and what makes this the right stopping "
                "point. **`the rest is in the backlog` is not a reason**: it says where the "
                "work went, not why it did not happen here. Effort that will not fit a review "
                "sitting is a reason; work that is merely more of the same is not, and the "
                "claim budget in R-11.3 is what tells you whether there was room for it.",
            )
        )


def check_open_questions(index, meta, by_kind, path, problems, meta_line=0):
    """Every open question the assessment raised must be accounted for.

    This is R-11.3's completeness rule applied to a different node type, and it exists for
    the same reason. Stage one names a question it deliberately did not answer — whether to
    commit a fixture directory, what a coverage threshold becomes — and gives it an
    identifier so the endpoint is not free text. Nothing then forces stage two to do anything
    with it, so a question could be dropped between the stages in silence.

    A question is accounted for when the plan escalates it, excludes it, backlogs it, or
    records that it resolved it. A *work item* referencing it does not count: a work item is
    planned work, not an answer, and an item built on an unanswered question is the failure
    this rule catches rather than the discharge of it.
    """
    questions = {
        q["id"]: q
        for q in index.get("open_questions", []) or []
        if isinstance(q, dict) and isinstance(q.get("id"), str)
    }
    if not questions:
        return

    accounted = {}
    for kind in ("escalation", "decision", "flagged", "exclusion", "backlog-item"):
        for block in by_kind.get(kind, []):
            for ref in block.node.get("assessment-ref") or []:
                if isinstance(ref, str):
                    accounted.setdefault(ref, []).append(
                        f"{kind} {block.node.get('id', '?')}"
                    )
    if meta is not None:
        for entry in meta.get("assessment_resolutions") or []:
            if isinstance(entry, dict) and isinstance(entry.get("ref"), str):
                accounted.setdefault(entry["ref"], []).append("assessment_resolutions")

    for question_id, question in sorted(questions.items()):
        if question_id in accounted:
            continue
        problems.append(
            Problem(
                "unconsumed-open-question",
                path,
                meta.line_of("assessment_resolutions", meta_line) if meta is not None else meta_line,
                f"the assessment raises open question {question_id} and the plan neither "
                "escalates, excludes, backlogs, nor resolves it",
                "Turn it into a `decision` block, exclude it with a reason, put it in the "
                "backlog, or record in `assessment_resolutions` that the plan settled it. "
                f"The question is: {question.get('question', '')[:160]}",
            )
        )


def check_assessment_refs(index, by_kind, path, problems):
    known = set()
    for section in ("findings", "recommendations", "exclusions", "degradations", "open_questions"):
        for entry in index.get(section, []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                known.add(entry["id"])

    for kind, blocks in sorted(by_kind.items()):
        for block in blocks:
            node = block.node
            refs = node.get("assessment-ref")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, str) and ref not in known:
                    problems.append(
                        Problem(
                            "dangling-assessment-ref",
                            path,
                            node.line_of("assessment-ref", block.fence_line),
                            f"{node.get('id', kind)} references assessment item {ref}, which "
                            "the assessment index does not define",
                        )
                    )

    contested = {
        entry["id"]
        for section in ("findings", "recommendations", "exclusions")
        for entry in index.get(section, []) or []
        if isinstance(entry, dict) and entry.get("contested") and isinstance(entry.get("id"), str)
    }
    if not contested:
        return

    meta = by_kind.get("plan-meta", [None])[0]
    resolved = set()
    if meta is not None:
        for entry in meta.node.get("assessment_resolutions") or []:
            if isinstance(entry, dict) and isinstance(entry.get("ref"), str):
                resolved.add(entry["ref"])
    escalated = set()
    for kind in ("escalation", "decision"):
        for block in by_kind.get(kind, []):
            escalated |= {r for r in (block.node.get("assessment-ref") or []) if isinstance(r, str)}

    for item_block in by_kind.get("work-item", []):
        node = item_block.node
        for ref in node.get("assessment-ref") or []:
            if ref in contested and ref not in resolved and ref not in escalated:
                problems.append(
                    Problem(
                        "contested-unresolved",
                        path,
                        node.line_of("assessment-ref", item_block.fence_line),
                        f"{node.get('id')} builds on {ref}, which the assessment marks "
                        "contested, and the plan neither resolves nor escalates it",
                        "R-4.3: a contested finding may not support a work item as it "
                        "stands. Resolve it against the evidence and record the resolution "
                        "in `assessment_resolutions`, or escalate it.",
                    )
                )


def check_degradations(index, meta, path, problems):
    if meta is None:
        return
    declared = {
        entry.get("id")
        for entry in meta.get("inherited_degradations") or []
        if isinstance(entry, dict)
    }
    for degradation in index.get("degradations", []) or []:
        if not isinstance(degradation, dict):
            continue
        if degradation.get("id") not in declared:
            problems.append(
                Problem(
                    "undeclared-degradation",
                    path,
                    meta.line_of("inherited_degradations", 1),
                    f"the assessment records degradation {degradation.get('id')} "
                    f"({degradation.get('degradation')!r}) and the plan does not say what it "
                    "costs this plan",
                    "R-13.3: the plan states which degradations it inherited and what each "
                    "one cost it.",
                )
            )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def render_waves(waves):
    lines = ["```yaml wave-schedule", "computed_by: plan_lint.py", "waves:"]
    for wave in waves:
        lines.append(f"  - wave: {wave['wave']}")
        lines.append("    slices:")
        for slice_id in wave["slices"]:
            lines.append(f"      - {slice_id}")
        lines.append(f'    reason: "{wave["reason"]}"')
    lines.append("```")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan", help="path to the plan file")
    parser.add_argument("--assessment", help="path to the assessment report, for R-11.3")
    parser.add_argument(
        "--phase",
        choices=PHASES,
        default="planned",
        help="where the plan is in its life: `planned` (default, freshly written), "
             "`reviewed` (the owner has written in resolutions and ratifications), or "
             "`executed` (stage three has written status back)",
    )
    parser.add_argument(
        "--ledger",
        help="path to docs/test-ledger.json. R-7.3 of the reporting document obligates the "
             "planner to consistency with the run ledger: an item touching a file that "
             "carries an open defect names it, and a claim the ledger already records at "
             "cited or ratified authority is not re-derived as new work",
    )
    parser.add_argument("--waves", action="store_true", help="print the computed wave schedule and exit")
    parser.add_argument("--scope", action="store_true",
                        help="print the computed scope figures and exit; needs --assessment")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args()

    problems, waves = lint(args.plan, args.assessment, args.phase, args.ledger)

    if args.scope:
        if not args.assessment:
            print("--scope needs --assessment: the figures come from the assessment's "
                  "testability data", file=sys.stderr)
            return 2
        by_kind, _, _ = planlib.load_plan(args.plan)
        index = load_assessment_index(args.assessment, [], args.plan)
        if index is None:
            print("could not read the assessment index", file=sys.stderr)
            return 2
        claims = {b.node.get("id"): b.node for b in by_kind.get("claim", [])}
        items = {b.node.get("id"): b.node for b in by_kind.get("work-item", [])}
        planned, available, entries = compute_scope(index, claims, items)
        share = (planned / available) if available else 0
        print("```yaml   # paste into plan-meta")
        print("scope:")
        print(f"  functions_planned: {planned}")
        print(f"  functions_available: {available}")
        print("  rationale: >")
        print(f"    # {planned} of {available} reachable classified functions, {share:.0%}. "
              "Say why the plan stops here.")
        print("```")
        unplanned = sorted(
            {(e.get("file"), e.get("function"), e.get("category"))
             for fs in index_testability(index).values() for e in fs
             if e.get("category") not in UNREACHABLE_CATEGORIES
             and (e.get("file"), e.get("function"), e.get("line")) not in entries}
        )
        if unplanned:
            print(f"\n{len(unplanned)} reachable function(s) no claim locates on:")
            for file, function, category in unplanned:
                print(f"  {file}:{function}  [{category}]")
        return 0

    if args.waves:
        if waves is None:
            print("could not compute waves: the plan did not parse", file=sys.stderr)
            return 2
        print(render_waves(waves))
        return 0

    problems.sort(key=lambda p: (p.line, p.rule))

    if args.json:
        print(
            json.dumps(
                {
                    "plan": args.plan,
                    "ok": not problems,
                    "problem_count": len(problems),
                    "problems": [p.as_dict() for p in problems],
                    "waves": waves,
                },
                indent=2,
            )
        )
    elif not problems:
        print(f"ok: {args.plan}")
        if waves:
            print(f"  {len(waves)} wave(s): " + "; ".join(
                f"{w['wave']}: {', '.join(w['slices'])}" for w in waves
            ))
        if not args.assessment:
            print(
                "  note: --assessment was not given, so the completeness rule (R-11.3) did "
                "not run. That is the linter's most important check."
            )
        for note in LAST_RUN_NOTES:
            print(f"  note: {note}")
    else:
        hard_stops = [p for p in problems if p.rule == UNCLASSIFIED_RULE]
        print(f"FAILED: {args.plan} — {len(problems)} problem(s)\n")
        for problem in problems:
            print(f"  {problem}")
        print()
        for note in LAST_RUN_NOTES:
            print(f"  note: {note}\n")
        if hard_stops:
            # Repeated at the end because it is the one failure whose remedy is not an edit
            # to this file, and it would otherwise scroll past above a long list of ordinary
            # lint failures.
            print(
                "  HARD STOP: the assessment must classify the locations listed above "
                "before this plan can be linted for claim enablement. Run the "
                "test-assessment skill in backfill mode against the report, then re-run "
                "this linter.\n"
            )

    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

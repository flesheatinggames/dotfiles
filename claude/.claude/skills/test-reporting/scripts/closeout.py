#!/usr/bin/env python3
"""The close-out gate: present every defect as a decision, then apply what the owner chose.

Two invocations with the owner's sitting between them.

``--brief`` writes `docs/test-closeout.md`: one section per defect carrying the claim, the
observed behavior, the red test, the four options with what each costs, and an empty answer
block. ``--apply`` reads the filled sheet back, validates it, performs each transformation,
verifies it through the check runner, commits it, and writes the records into the plan.

**Why an answer sheet rather than the plan file.** Stage two's review gate has the owner write
their resolutions into the plan itself, and the reasoning that puts them there — nothing
rewrites the plan on the owner's behalf — applies here with more force, because one of these
answers ends with a real failure being marked as expected. What does not carry over is the
timing. A close-out record is only complete once its consequence has been applied and verified,
so a plan carrying the owner's answers and not yet their consequences would sit at neither lint
phase: past `executed`, short of `closed`. The answer sheet is the intermediate state, held in
a file of its own, and the plan moves from one lintable phase to the next in a single step.

**One sitting.** Section 11 of the requirements leaves splitting the gate across sittings open
and the first version treats it as one, which this implements: `--apply` refuses a partially
filled sheet rather than persisting half a gate. A half-answered gate is decision debt that
looks like progress.

**What this script may edit.** R-6.3 confines the close-out executor to the named test of the
decision being applied — nothing else, and in particular no production code. Fixing a defect is
the owner's work outside this charter; `fix-the-code` is therefore an answer that applies
nothing. The footprint of every consequence commit is measured with stage three's `actuals.py`
and an edit outside that surface aborts the whole close-out rather than that one decision.

Usage:
    python3 closeout.py docs/test-plan.md --repo . --brief
    python3 closeout.py docs/test-plan.md --repo . --apply
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import siblings  # noqa: E402

planlib = siblings.planlib()

DEFAULT_SHEET = "docs/test-closeout.md"
DEFAULT_LOG_DIR = "docs/test-execution-log"

OPTIONS = ("fix-the-code", "requirement-wrong", "accept-with-red", "downgrade")

# What each option costs, written to the owner rather than to the model. These are the
# sentences the gate is actually decided on, so they say what the answer does to the branch,
# to the ledger, and to every later run — not what the requirement calls it.
OPTION_TEXT = {
    "fix-the-code": (
        "The code is wrong and someone will fix it. Nothing changes on this branch now: the "
        "red test stays red and becomes the ready-made verification for whoever does the fix. "
        "The defect stays open in the run ledger and every later run re-reports it until the "
        "test goes green. Cost: the suite is red until then, so anything that gates on a green "
        "suite is blocked."
    ),
    "requirement-wrong": (
        "The claim was wrong and what the code does is acceptable. The failing test is "
        "rewritten to assert the observed behavior, the claim is relabelled "
        "`ratified-as-observed`, and the document that specified something else is flagged for "
        "amendment. Cost: a behavior that a document called specified becomes a behavior the "
        "code merely has, and the document is now known to be wrong until somebody amends it."
    ),
    "accept-with-red": (
        "The defect is real, the branch merges anyway, and continuous integration carries the "
        "enforcement rather than this suite. Nothing changes on this branch. Cost: the same as "
        "`fix-the-code` with no expectation of a fix, so the red becomes background noise "
        "unless something outside the repository is watching it."
    ),
    "downgrade": (
        "A known-failure marker is applied so the suite reports green over a defect that is "
        "still real. **This answer is available to nobody but you.** No agent may reach it, "
        "not at any point in this pipeline, because a cited claim carries a requirements "
        "document's authority and a ratified claim carries yours personally — and the "
        "authority to declare either non-blocking belongs to whoever made it binding. Cost: "
        "the failure stops being visible, which is the point and also the risk."
    ),
}

RED_TEST_STATE = {
    "fix-the-code": "standing",
    "accept-with-red": "standing",
    "requirement-wrong": "rewritten",
    "downgrade": "marked",
}

CLOSEOUT_INTRO = """\
The owner's answer to every defect, and what each answer did to the branch (R-6.1, R-6.2). One
record per registry entry, one commit per consequence, each verified by the check runner before
the gate advanced. Nothing here was decided by the pipeline; `decided-by` names the person."""

DISPUTE_INTRO = """\
R-6.5's optional answers on impeached pinned claims. A dispute is a planner error with evidence
captured and nothing red on the branch, so it does not block close-out and leaving one open is
a legitimate outcome — it stays an open run-ledger item and feeds the planner-accuracy
finding."""


class CloseoutError(Exception):
    """The gate cannot proceed. Always carries what to do about it."""


def git(repo, *arguments):
    return subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True)


def _key(identifier):
    text = identifier or ""
    tail = text.rstrip("0123456789")
    number = text[len(tail):]
    return (tail, int(number) if number else 0)


# --------------------------------------------------------------------------------------
# The brief
# --------------------------------------------------------------------------------------


def render_brief(plan, repo):
    """One decision per defect, with everything needed to answer it without running anything."""
    lines = []
    add = lines.append
    repository = (plan.meta.node.get("repository") if plan.meta else None) or repo

    add(f"# Close-out gate — {repository}")
    add("")
    add(
        "This run is not closed until every defect below carries your answer. Each one is a "
        "place where the code contradicted a claim that carries a requirements document's "
        "authority or yours personally, and each has a test standing red on the branch as the "
        "evidence."
    )
    add("")
    add(
        "Write your answer into the `answer` block under each defect, then run the apply "
        "command at the bottom of this file. Nothing writes an answer for you, and a "
        "half-filled sheet is refused rather than half-applied."
    )
    add("")
    add("## The four answers")
    add("")
    for option in OPTIONS:
        add(f"**`{option}`** — {OPTION_TEXT[option]}")
        add("")
    add("---")
    add("")

    defects = sorted(plan.defects.items(), key=lambda kv: _key(kv[0]))
    if not defects:
        add("## No defects")
        add("")
        add(
            "This run surfaced no defects, so the gate is empty and the run closes without "
            "decisions. That is a real outcome rather than a formality: it means every claim "
            "the plan asserted held against the code as written."
        )
        add("")
    for defect_id, block in defects:
        node = block.node
        claim_id = node.get("claim")
        claim = plan.claims.get(claim_id)
        test = node.get("test") or {}
        add(f"## {defect_id}")
        add("")
        add(f"**The claim.** {claim_id}"
            + (f" ({claim.node.get('label')})" if claim else "")
            + ": " + (claim.node.get("text") if claim else "_claim not found in the plan_"))
        if claim is not None:
            source = claim.node.get("source") or {}
            if source.get("kind") == "document":
                add("")
                add(f"Its authority comes from `{source.get('location')}`, which says: "
                    f"“{source.get('quote')}”")
            elif claim.node.get("ratified-by"):
                add("")
                add(f"You ratified this on {claim.node.get('ratified-on')}.")
        add("")
        add(f"**What the code actually does.** {node.get('observed')}")
        add("")
        add(f"**The red test.** `{test.get('name')}` in `{test.get('file')}`, committed at "
            f"`{node.get('commit')}`.")
        verification = node.get("verification") or {}
        if verification:
            add("")
            add(
                f"Before this test was allowed to stand red, a fresh-context verifier was given "
                f"the claim's text and the test and nothing else, and returned "
                f"`{verification.get('verdict')}`: {verification.get('note')}"
            )
        suspended = node.get("suspended-mutations") or []
        if suspended:
            add("")
            add(
                "While this test is red, the mutation checks for "
                + ", ".join(suspended)
                + " prove nothing and are recorded suspended rather than passed. They activate "
                "when it goes green."
            )
        if node.get("note"):
            add("")
            add(node["note"])
        add("")
        add("```yaml answer")
        add(f"defect: {defect_id}")
        add("option:            # fix-the-code | requirement-wrong | accept-with-red | downgrade")
        add("decided-by:        # your name; a decision with no decider is not a decision")
        add("date:              # \"YYYY-MM-DD\", quoted")
        add("rationale: >")
        add("  # Why this answer rather than the other three. The next run re-reports an open")
        add("  # defect and the reader needs to know what was already weighed.")
        add("")
        add("# Only for `requirement-wrong`:")
        add("# amendment-document: docs/spec.md")
        add("# amendment-passage: \"the sentence that is now known to be wrong\"")
        add("")
        add("# Only for `downgrade`. Leave it out and a pytest marker is written for you;")
        add("# supply it when the runner is not pytest.")
        add("# marker-form: \"@pytest.mark.xfail(reason='DF-1: downgraded at close-out')\"")
        add("```")
        add("")
        add("---")
        add("")

    disputes = sorted(
        (claim_id for claim_id, block in plan.claims.items()
         if block.node.get("label") == "disputed"),
        key=_key,
    )
    if disputes:
        add("## Disputes — for information, and answering is optional")
        add("")
        add(
            "Each of these is a claim the planner read out of the code that a faithful test "
            "then contradicted. Nothing is red on the branch and nothing blocks the merge: the "
            "claim's only backing was the planner's reading, so the failure impeaches the "
            "reading. Answering one records a correction for the next round of planning. "
            "Leaving one open is a legitimate answer and it stays on the run ledger."
        )
        add("")
        for claim_id in disputes:
            node = plan.claims[claim_id].node
            add(f"### {claim_id}")
            add("")
            add(f"**As planned.** {node.get('text')}")
            add("")
            add(f"**Evidence of the contradiction.** `{node.get('evidence')}`")
            if node.get("notes"):
                add("")
                add(node["notes"])
            add("")
            add("```yaml dispute-answer")
            add(f"claim: {claim_id}")
            add("option:            # correct-the-claim | leave-disputed")
            add("decided-by:")
            add("date:              # \"YYYY-MM-DD\", quoted")
            add("# corrected-text: >   # required for correct-the-claim")
            add("#   The claim as it should have been written.")
            add("```")
            add("")
        add("---")
        add("")

    add("## When the sheet is filled")
    add("")
    add("```bash")
    add("python3 <skill>/scripts/closeout.py docs/test-plan.md --repo . --apply")
    add("```")
    add("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Reading the sheet back
# --------------------------------------------------------------------------------------


def read_sheet(path):
    """The owner's answers, parsed with the same YAML subset the plan uses."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise CloseoutError(
            f"cannot read the answer sheet at {path}: {error}. Run --brief first, hand the "
            "sheet to the owner, and run --apply once it is filled."
        ) from error

    answers, dispute_answers = {}, {}
    for block in planlib.extract_blocks(text):
        if block.kind not in ("answer", "dispute-answer"):
            continue
        try:
            node = planlib.parse_yaml(block.body, first_line=block.body_start_line)
        except planlib.PlanYamlError as error:
            raise CloseoutError(
                f"{path}:{error.line}: the answer block does not parse: {error.message}"
                + (f"\n    {error.fix}" if error.fix else "")
            ) from error
        if not isinstance(node, dict):
            continue
        if block.kind == "answer":
            answers[node.get("defect")] = (node, block.fence_line)
        else:
            dispute_answers[node.get("claim")] = (node, block.fence_line)
    return answers, dispute_answers


def validate_answers(plan, answers, path):
    """Every defect answered, every answer complete, and the one restricted option guarded."""
    problems = []
    for defect_id in sorted(plan.defects, key=_key):
        entry = answers.get(defect_id)
        if entry is None:
            problems.append(
                f"{defect_id} has no answer block in {path}. R-6.1: the run is not closed "
                "until every registry entry carries one."
            )
            continue
        node, line = entry
        option = node.get("option")
        if option not in OPTIONS:
            problems.append(
                f"{path}:{line}: {defect_id}'s `option` is {option!r}; it must be one of "
                + ", ".join(OPTIONS)
            )
        if not (node.get("decided-by") or "").strip():
            problems.append(
                f"{path}:{line}: {defect_id} names no decider. A decision with no decider is "
                "one an agent could have made."
            )
        if not (node.get("date") or "").strip():
            problems.append(f"{path}:{line}: {defect_id} carries no date")
        rationale = (node.get("rationale") or "").strip()
        if len(rationale) < 30:
            problems.append(
                f"{path}:{line}: {defect_id}'s rationale is {len(rationale)} characters. Say "
                "why this answer rather than the other three; a later run re-reports an open "
                "defect and the reader needs to know what was already weighed."
            )
        if option == "requirement-wrong":
            for field in ("amendment-document", "amendment-passage"):
                if not (node.get(field) or "").strip():
                    problems.append(
                        f"{path}:{line}: {defect_id} chose `requirement-wrong` and gives no "
                        f"`{field}`. R-6.4: accepting the observed behavior means a document "
                        "is now known to be wrong, and the flag is what stops that being "
                        "forgotten."
                    )
        if option == "downgrade":
            decider = (node.get("decided-by") or "").strip().lower()
            if decider in {"claude", "agent", "assistant", "bot", "ci", "automation",
                           "executor", "unknown", "n/a", "none", ""}:
                problems.append(
                    f"{path}:{line}: {defect_id} downgrades a real defect and names "
                    f"{node.get('decided-by')!r} as the decider. This answer is the owner's "
                    "and nobody else's."
                )

    unknown = sorted(set(answers) - set(plan.defects))
    for defect_id in unknown:
        problems.append(
            f"{path}: an answer block names {defect_id!r}, which the defect registry does not "
            "hold"
        )
    return problems


# --------------------------------------------------------------------------------------
# Applying a decision
# --------------------------------------------------------------------------------------


def apply_marker(repo, test_file, test_name, form, defect_id):
    """Write a known-failure marker above the named test. Returns the form written.

    pytest is written for; anything else is a stop naming what to insert. Guessing a marker
    syntax for a runner this has not been shown is exactly the shape of failure that produces a
    suite reporting green for a reason nobody can find.
    """
    full = os.path.join(repo, test_file)
    if not os.path.exists(full):
        raise CloseoutError(f"{defect_id}: the test file {test_file} does not exist")
    with open(full, encoding="utf-8") as handle:
        lines = handle.read().split("\n")

    bare = test_name.split("::")[-1]
    target = None
    for index, line in enumerate(lines):
        if re.match(rf"^\s*(?:async\s+)?def\s+{re.escape(bare)}\s*\(", line):
            target = index
            break
    if target is None:
        if not full.endswith(".py"):
            raise CloseoutError(
                f"{defect_id}: {test_file} is not a Python file, so no marker was written. "
                "Supply `marker-form` in the answer block with the marker your runner uses — "
                "`it.failing(...)` for vitest, `test.failing(...)` for jest — apply it "
                "yourself, and re-run --apply. A guessed marker syntax is a suite reporting "
                "green for a reason nobody can find."
            )
        raise CloseoutError(
            f"{defect_id}: no `def {bare}` was found in {test_file}, so the marker had "
            "nowhere to go. Check the test name in the defect registry against the file."
        )

    if form is None:
        form = (
            f'@pytest.mark.xfail(strict=True, reason="{defect_id}: downgraded at close-out; '
            'the defect is real and the marker is the owner\'s recorded decision")'
        )
    indent = " " * (len(lines[target]) - len(lines[target].lstrip()))

    insert_at = target
    while insert_at > 0 and lines[insert_at - 1].strip().startswith("@"):
        insert_at -= 1
    lines.insert(insert_at, indent + form)

    if "pytest.mark" in form and not any(
        re.match(r"^\s*import pytest\b", line) for line in lines
    ):
        lines.insert(0, "import pytest")

    with open(full, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return form


def verify(plan, repo, log_dir, defect_id, option, timeout):
    """Run the check runner against what the decision claims it left behind (R-6.2).

    Two checks for every option and they are asking different questions. The narrow one asks
    whether this decision's own test is in the state the decision says; the wide one asks
    whether the suite as a whole is where the run left it, minus whatever this decision just
    changed. Only the second would catch a marker applied to the wrong test.
    """
    check_runner = siblings.check_runner()
    node = plan.defects[defect_id].node
    test = node.get("test") or {}
    command, _ = check_runner.coverage_source(plan)
    if not command:
        return [check_runner.record(
            "tests-pass", "not-run",
            "the plan does not name a suite command, so this consequence could not be verified",
        )]

    expect = "named-tests-fail" if RED_TEST_STATE[option] == "standing" else "all-pass"
    narrow = check_runner.check_tests_pass(
        {
            "kind": "tests-pass",
            "command": command,
            "tests": [test.get("name")],
            "expect": expect,
        },
        repo, log_dir, timeout,
        allowed=_still_red(plan, defect_id, option),
    )

    inherited = _inherited_failures(repo, log_dir)
    wide = check_runner.check_standing_invariant(
        plan, repo, log_dir, command, inherited,
        _still_red(plan, defect_id, option), timeout,
    )
    return [narrow, wide]


def _still_red(plan, applying, option):
    """The registry tests that are expected to be failing after this decision lands.

    The decision being applied is excluded when its own answer takes the red away, and included
    when it does not. Getting this wrong in the permissive direction would let a decision that
    silently broke something else pass its own verification.
    """
    names = []
    for defect_id, block in plan.defects.items():
        test = block.node.get("test") or {}
        name = test.get("name")
        if not name:
            continue
        if defect_id == applying and RED_TEST_STATE[option] != "standing":
            continue
        names.append(name)
    return names


def _inherited_failures(repo, log_dir):
    path = os.path.join(repo, log_dir, "preflight.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        record = json.load(handle)
    return list((record.get("baseline") or {}).get("inherited_failures") or [])


def commit_consequence(repo, paths, defect_id, option, rationale):
    """One commit per decision, holding exactly the files the decision was allowed to touch."""
    for path in paths:
        result = git(repo, "add", "--", path)
        if result.returncode != 0:
            raise CloseoutError(f"{defect_id}: `git add {path}` failed: {result.stderr.strip()}")
    message = (
        f"close-out: {defect_id} {option}\n\n{rationale.strip()}\n\n"
        "Applied by the close-out gate (R-6.2). One commit per decision."
    )
    result = git(repo, "commit", "-m", message)
    if result.returncode != 0:
        raise CloseoutError(
            f"{defect_id}: the consequence commit failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def measure_surface(plan, repo, commit, defect_id, allowed):
    """R-6.3: everything the consequence commit touched, against what it was allowed to touch."""
    actuals = siblings.actuals()
    paths, problem = actuals.files_in_commit(repo, commit)
    if problem:
        raise CloseoutError(
            f"{defect_id}: the consequence commit's footprint could not be measured — {problem}"
            "\n\nR-6.3 confines this stage's edit surface to the decision's named test, and an "
            "unmeasured surface is an unenforced rule. The close-out stops rather than "
            "proceeding on the assumption that the commit contained what it was meant to."
        )
    touched = set(paths)
    outside = sorted(touched - set(allowed))
    if outside:
        raise CloseoutError(
            f"{defect_id}: the consequence commit {commit[:7]} touched "
            f"{len(outside)} file(s) outside the decision's edit surface: "
            + ", ".join(outside)
            + ".\n\nR-6.3 confines the close-out executor to the named test of the decision "
            "being applied. The whole close-out stops here rather than this one decision, "
            "because an edit nobody authorised has already landed and the remaining decisions "
            "would be applied on top of it. Reset the commit, undo the extra edit, and run "
            "--apply again."
        )
    return sorted(touched)


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


def apply_all(plan, answers, dispute_answers, repo, log_dir, sheet_path, timeout, dry_run):
    planio = siblings.planio()
    applied = []
    flag_number = _next_flag_number(plan)

    for index, defect_id in enumerate(sorted(plan.defects, key=_key), start=1):
        node, _ = answers[defect_id]
        option = node["option"]
        state = RED_TEST_STATE[option]
        test = plan.defects[defect_id].node.get("test") or {}
        test_file = test.get("file")
        closeout_id = f"CO-{index}"

        marker = None
        commit = None
        touched = []

        if option == "requirement-wrong":
            _require_rewritten(plan, repo, log_dir, defect_id, test, timeout)
        elif option == "downgrade" and not dry_run:
            marker_form = apply_marker(
                repo, test_file, test.get("name"), node.get("marker-form"), defect_id
            )
            marker = {"file": test_file, "form": marker_form}

        checks = (
            [{"kind": "tests-pass", "outcome": "not-run",
              "detail": "--dry-run was passed, so nothing was verified"}]
            if dry_run else
            [_as_plain(check) for check in verify(plan, repo, log_dir, defect_id, option, timeout)]
        )
        failed = [check for check in checks if check.get("outcome") == "failed"]
        if failed and not dry_run:
            raise CloseoutError(
                f"{defect_id}: the consequence did not verify — "
                + "; ".join(check.get("detail") or "" for check in failed)
                + ".\n\nR-6.2 verifies each consequence before the gate advances, so the gate "
                "stops here. Nothing has been committed for this decision."
            )

        if option in ("requirement-wrong", "downgrade") and not dry_run:
            commit = commit_consequence(
                repo, [test_file], defect_id, option, node.get("rationale") or ""
            )
            touched = measure_surface(plan, repo, commit, defect_id, [test_file])

        fields = {
            "id": closeout_id,
            "defect": defect_id,
            "option": option,
            "decided-by": node.get("decided-by"),
            "date": node.get("date"),
            "rationale": node.get("rationale"),
            "red-test-state": state,
            "commit": commit,
            "checks": checks,
        }
        if option == "requirement-wrong":
            fields["amendment-flag"] = {
                "id": f"DA-{flag_number}",
                "document": node.get("amendment-document"),
                "passage": node.get("amendment-passage"),
                "note": (
                    f"Raised by {closeout_id}. The document specifies behavior the code does "
                    "not have, and the owner accepted the code. Tracked in the run ledger "
                    "until the document is amended or the flag is contested (R-6.4)."
                ),
            }
            flag_number += 1
        if marker is not None:
            fields["marker"] = marker

        applied.append({
            "closeout": fields,
            "defect": defect_id,
            "option": option,
            "claim": plan.defects[defect_id].node.get("claim"),
            "touched": touched,
        })

    if dry_run:
        return applied

    for entry in applied:
        _write_decision(plan, planio, entry)

    for claim_id, (node, _) in sorted(dispute_answers.items(), key=lambda kv: _key(kv[0])):
        if not node.get("option"):
            continue
        fields = {
            "claim": claim_id,
            "option": node.get("option"),
            "decided-by": node.get("decided-by"),
            "date": node.get("date"),
        }
        if node.get("corrected-text"):
            fields["corrected-text"] = node["corrected-text"]
        if node.get("rationale"):
            fields["rationale"] = node["rationale"]
        plan.upsert_block(
            planio.DISPUTE_SECTION, "dispute-decision", fields, {"claim": claim_id},
            intro=DISPUTE_INTRO,
        )

    return applied


def _write_decision(plan, planio, entry):
    """The close-out block, the resolution, and — for one option — the claim's new label.

    All three inside one transaction, because two of the linter's rules are mirror images: a
    `requirement-wrong` decision whose claim is not relabelled fails, and a relabelled claim
    with no decision behind it fails. Whichever were written first would introduce the other's
    failure and be rolled back on its own.
    """
    fields = entry["closeout"]
    with plan.transaction(f"close-out of {entry['defect']}"):
        if entry["option"] == "requirement-wrong" and entry["claim"]:
            plan.set_field("claim", entry["claim"], "label", "ratified-as-observed")
            # `ratified-as-observed` is a ratification and the linter holds it to a
            # ratification's record. It says the owner judged a specified behavior wrong and
            # accepted what the code does, which is a decision with an author and a date.
            plan.set_field("claim", entry["claim"], "ratified-by", fields["decided-by"])
            plan.set_field("claim", entry["claim"], "ratified-on", fields["date"])
        plan.upsert_block(
            planio.CLOSEOUT_SECTION, "close-out", fields, {"id": fields["id"]},
            intro=CLOSEOUT_INTRO,
        )
        plan.set_field("defect", entry["defect"], "resolution", entry["option"])


def _require_rewritten(plan, repo, log_dir, defect_id, test, timeout):
    """`requirement-wrong` needs the test rewritten first, and this is where that is checked.

    The rewrite is the single judgment stage four retains, exactly parallel to stage three
    retaining only "how to express a claim as a test". A script cannot write an assertion about
    observed behavior that is worth having — it would produce a test asserting whatever the code
    currently returns, which is a characterization pin wearing a specification's label.
    """
    check_runner = siblings.check_runner()
    command, _ = check_runner.coverage_source(plan)
    if not command:
        return
    result = check_runner.check_tests_pass(
        {
            "kind": "tests-pass",
            "command": command,
            "tests": [test.get("name")],
            "expect": "all-pass",
        },
        repo, log_dir, timeout,
        allowed=_still_red(plan, defect_id, "requirement-wrong"),
    )
    if result.get("outcome") == "passed":
        return
    raise CloseoutError(
        f"{defect_id} chose `requirement-wrong` and `{test.get('name')}` in "
        f"`{test.get('file')}` is still failing.\n\n"
        "This answer means the test is rewritten to assert what the code actually does, and "
        "writing that assertion is the one judgment this stage retains — a script that "
        "generated it would produce a test asserting whatever the code currently returns, "
        "which is a characterization pin wearing a specification's label.\n\n"
        "Rewrite the test against the `observed` field of the registry entry, keep the "
        f"`# claim: {plan.defects[defect_id].node.get('claim')}` annotation on it, change "
        "nothing outside that file, and run --apply again.\n\n"
        f"The runner reported: {result.get('detail')}"
    )


def _as_plain(check):
    """One check-runner result as the schema's recorded-check shape."""
    out = {"kind": check.get("kind"), "outcome": check.get("outcome")}
    for field in ("claim", "detail", "log"):
        if check.get(field):
            out[field] = check[field]
    return out


def _next_flag_number(plan):
    highest = 0
    for block in plan.closeouts.values():
        flag = block.node.get("amendment-flag")
        if isinstance(flag, dict) and isinstance(flag.get("id"), str):
            tail = flag["id"].split("-")[-1]
            if tail.isdigit():
                highest = max(highest, int(tail))
    return highest + 1


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--assessment")
    parser.add_argument("--sheet", default=DEFAULT_SHEET)
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--brief", action="store_true", help="write the decision sheet")
    parser.add_argument("--apply", action="store_true", help="read it back and apply it")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the sheet and report what would be applied")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    if not (args.brief or args.apply):
        parser.error("pass --brief to write the decision sheet or --apply to apply it")

    planio = siblings.planio()
    phase = "closed" if args.apply and not args.dry_run else "executed"
    plan = planio.Plan(
        args.plan, assessment=args.assessment, phase=phase,
        lint_writes=args.apply and not args.dry_run,
    )

    sheet_path = (
        args.sheet if os.path.isabs(args.sheet) else os.path.join(args.repo, args.sheet)
    )

    if args.brief:
        os.makedirs(os.path.dirname(os.path.abspath(sheet_path)), exist_ok=True)
        with open(sheet_path, "w", encoding="utf-8") as handle:
            handle.write(render_brief(plan, args.repo))
        print(f"wrote {args.sheet} — {len(plan.defects)} decision(s) for the owner")
        if not plan.defects:
            print("  The gate is empty: this run surfaced no defects. Run --apply to close it.")
        else:
            print("  Hand this to the owner. Nothing writes an answer on their behalf, and one "
                  "of the four options is not available to anybody else at all.")
        return 0

    try:
        answers, dispute_answers = read_sheet(sheet_path)
        problems = validate_answers(plan, answers, args.sheet)
        if problems:
            print(f"FAILED: the close-out gate cannot proceed — {len(problems)} problem(s)\n",
                  file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            print("\n  R-6.1 makes this one sitting: a partially answered gate is refused "
                  "rather than half-applied, because half a gate is decision debt that looks "
                  "like progress.\n", file=sys.stderr)
            return 1

        applied = apply_all(
            plan, answers, dispute_answers, args.repo, args.log_dir, args.sheet,
            args.timeout, args.dry_run,
        )
    except CloseoutError as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 2
    except planio.WriteRejected as rejected:
        print(str(rejected), file=sys.stderr)
        return 1

    verb = "would apply" if args.dry_run else "applied"
    print(f"{verb} {len(applied)} decision(s):")
    for entry in applied:
        fields = entry["closeout"]
        commit = fields.get("commit")
        print(f"  {fields['id']}  {entry['defect']} → {entry['option']}"
              + (f", committed {commit[:7]}" if commit else ", nothing applied"))
        if entry["touched"]:
            print(f"       touched: {', '.join(entry['touched'])}")
    if dispute_answers and not args.dry_run:
        answered = [c for c, (n, _) in dispute_answers.items() if n.get("option")]
        print(f"  {len(answered)} dispute(s) answered, "
              f"{len(dispute_answers) - len(answered)} left open")
    if not args.dry_run:
        print("\nNext: run_record.py --write --phase closed, then findings.py --write, then "
              "assemble.py, then trace_report.py, then ledger.py --append.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

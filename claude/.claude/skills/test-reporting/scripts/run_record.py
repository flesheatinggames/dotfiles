#!/usr/bin/env python3
"""Assemble the run record: the single source for every figure the report states (R-4.1, R-4.2).

**It re-derives nothing.** Stage three's run summary is copied forward unchanged — items,
claims, defects, disputes, coverage, footprint, inherited failures, narrowings — and stage four
adds only what stage three could not know: the close-out decisions, their consequence commits,
the final suite state, the pipeline findings, and the ledger entry this run appended.

That restraint is a requirement rather than an economy. A second derivation of the same figure
is a second opinion, and this project has twice been bitten by two copies of one statement
drifting apart. So where a figure is missing from the summary it is reported missing and raised
as a pipeline finding against stage three, never reconstructed here — a reconstructed figure is
indistinguishable in the report from a measured one, and the whole epistemology of the report
rests on that distinction being visible.

**R-4.2 is the other half.** Before anything is assembled, the summary is checked against the
plan writeback: statuses agree, every registry entry has a committed test, every commit on the
branch is named by an item or a decision. Each check is recorded in the record itself rather
than merely performed, because R-9.3 requires degradation to be stated with its cost, and a
report can only state a cost it can see.

Usage:
    python3 run_record.py docs/test-plan.md --repo .
    python3 run_record.py docs/test-plan.md --repo . --write     # the run-record block
    python3 run_record.py docs/test-plan.md --repo . --json
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

DEFAULT_LOG_DIR = "docs/test-execution-log"
DEFAULT_LEDGER = "docs/test-ledger.json"
DEFAULT_REPORT = "docs/test-report.md"

RECORD_INTRO = """\
Machine-readable, derived, and the single source for every figure in `docs/test-report.md`
(R-5.1). Stage three's run summary copied forward unchanged, plus what only the close-out gate
knows: the owner's decisions, the commits their consequences landed in, the suite as it stands
now, and what this run says about the pipeline itself. `trace_report.py` proves every number in
the report's prose against this block."""

# What the record is allowed to say about the suite when nobody could run it. R-9.2: a figure
# that was not measured is reported absent, never estimated.
UNMEASURED_SUITE = {
    "command": "",
    "passed": None,
    "failed": None,
    "expected_failures": [],
    "measured": False,
}


# --------------------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------------------


def git(repo, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=repo, capture_output=True, text=True
    )


def commit_exists(repo, sha):
    if not sha:
        return False
    return git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def commits_between(repo, base, head="HEAD"):
    if not base:
        return []
    result = git(repo, "rev-list", f"{base}..{head}")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.split("\n") if line.strip()]


def short(sha):
    return (sha or "")[:7]


# The files this pipeline writes about itself. A commit touching only these is bookkeeping.
_ARTIFACT_PREFIXES = ("docs/test-execution-log/",)
_ARTIFACT_FILES = {
    "docs/test-plan.md",
    "docs/test-assessment.md",
    "docs/test-report.md",
    "docs/test-closeout.md",
    "docs/test-ledger.json",
}


def _only_artifacts(repo, sha):
    """Whether a commit touched nothing but the pipeline's own documents."""
    result = git(repo, "show", "--name-only", "--format=", sha)
    if result.returncode != 0:
        return False
    paths = [line.strip() for line in result.stdout.split("\n") if line.strip()]
    if not paths:
        return False
    return all(
        path in _ARTIFACT_FILES or path.startswith(_ARTIFACT_PREFIXES) for path in paths
    )


# --------------------------------------------------------------------------------------
# Reading the suite as it now stands
# --------------------------------------------------------------------------------------

# A line the runner has labelled as its count of *tests*. Both vitest and jest print two
# tallies — one for files and one for tests — and the file tally comes first:
#
#      Test Files  8 passed (8)
#           Tests  30 passed (30)
#
# Reading the first one is not a near miss. It reported a thirty-test suite as eight tests and
# it did it on the first real repository this was pointed at, which is how it was found. So the
# labelled line is looked for explicitly, and it is looked for from the bottom up, because a
# runner prints its summary last and a test's own name can contain anything.
_TEST_LINE_RE = re.compile(r"^\s*Tests[:\s]")
_PASSED_RE = re.compile(r"(?<![\w.])(\d+)\s+passed")
_FAILED_RE = re.compile(r"(?<![\w.])(\d+)\s+failed")


def tally(output):
    """Passing and failing counts out of reporter output, or (None, None).

    This reads counts; `suite.failing_tests` reads names. They are different questions, the
    answers come from different lines of the same output, and this is not a second copy of that
    function. Where the two disagree — a summary line saying two failed and one recognised
    failure name — the record says so and the report inherits the doubt rather than resolving it.

    Two shapes, tried in order: a line the runner labels `Tests` (vitest, jest), then the last
    line mentioning a pass count at all (pytest's `==== 12 passed, 1 failed in 0.41s ====`).
    Anything unrecognised produces `measured: false` and null counts rather than a number
    nobody can defend, which is the standard the execution stage's failure classification is
    already held to.
    """
    lines = [line for line in output.split("\n") if line.strip()]
    for line in reversed(lines):
        if _TEST_LINE_RE.match(line):
            return _counts(line)
    for line in reversed(lines):
        if _PASSED_RE.search(line) or _FAILED_RE.search(line):
            return _counts(line)
    return None, None


def _counts(line):
    passed = _PASSED_RE.search(line)
    failed = _FAILED_RE.search(line)
    if not passed and not failed:
        return None, None
    return (
        int(passed.group(1)) if passed else 0,
        int(failed.group(1)) if failed else 0,
    )


def final_suite(plan, repo, log_dir, timeout, command=None):
    """The suite after every close-out consequence landed.

    The most-read figure in the report after coverage, and the one a reader will take to mean
    "everything is fine" unless the standing reds are named beside it. So the expected failures
    are carried with the counts rather than in a footnote: a green suite over a downgraded
    defect and a green suite with nothing wrong look identical from the number alone.
    """
    check_runner = siblings.check_runner()
    suite = siblings.suite()

    if command is None:
        command, _ = check_runner.coverage_source(plan)
    if not command:
        record = dict(UNMEASURED_SUITE)
        record["note"] = (
            "the plan does not say how to run the suite: slice zero carries no `tests-pass` "
            "command. Pass --suite-command to measure it."
        )
        return record

    result = suite.run(command, repo, timeout)
    failures, basis = suite.failing_tests(result.output)
    passed, failed = tally(result.output)

    log_path = os.path.join(repo, log_dir, "final-suite.txt")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(f"$ {command}\n\n{result.output}")

    if result.timed_out:
        record = dict(UNMEASURED_SUITE)
        record["command"] = command
        record["note"] = f"the suite timed out after {timeout}s, so nothing was measured"
        return record

    if basis == "unrecognised" and not result.ok:
        record = dict(UNMEASURED_SUITE)
        record["command"] = command
        record["note"] = (
            f"the suite exited {result.returncode} and no recognised reporter format was found "
            "in its output, so which tests failed could not be read. The state of the suite is "
            "unknown and is reported as unknown."
        )
        return record

    record = {
        "command": command,
        "passed": passed,
        "failed": failed if failed is not None else len(failures),
        "expected_failures": sorted(failures),
        "measured": True,
        "log": os.path.join(log_dir, "final-suite.txt"),
    }
    if passed is None:
        record["measured"] = False
        record["passed"] = None
        record["failed"] = None
        record["note"] = (
            f"the suite exited {result.returncode} and {len(failures)} failing test name(s) "
            "were read, but no summary line the tally recognises. The names are reported and "
            "the counts are not, because a count nobody read is a count nobody can check."
        )
    elif failed and len(failures) != failed:
        record["note"] = (
            f"the summary line reports {failed} failure(s) and {len(failures)} failing test "
            "name(s) were recognised. The two readings disagree; the names are the more "
            "specific of the two and the disagreement is stated rather than resolved."
        )
    return record


# --------------------------------------------------------------------------------------
# R-4.2: is the summary consistent with the plan it was derived from?
# --------------------------------------------------------------------------------------


def consistency_checks(plan, summary, repo, close_commit=None):
    """Every cross-check R-4.2 names, each recorded with what it found.

    ``close_commit`` bounds the run. It is HEAD while the record is being assembled and the
    recorded close commit once the gate has been held — see `build`, which explains why the
    difference matters.

    Recorded rather than only performed. A stage that checks and then reports only success has
    made the check invisible, and R-9.3 requires degradation to be stated with its cost to the
    report's confidence — which the report can only do if the failures survive into the record.
    """
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    if summary is None:
        add("run-summary-present", False,
            "the plan carries no `run-summary` block and no sidecar copy was found, so there "
            "is nothing to report from. Run run_summary.py --write in the execution skill.")
        return checks
    add("run-summary-present", True, "the run summary was read from the plan")

    # 1. Statuses agree.
    recorded = {}
    for entry in summary.get("items") or []:
        for item_id in entry.get("ids") or []:
            recorded[item_id] = entry.get("status")
    actual = {
        item_id: block.node.get("status") for item_id, block in plan.items.items()
    }
    disagreements = sorted(
        f"{item_id}: summary says {recorded.get(item_id)!r}, plan says {actual[item_id]!r}"
        for item_id in actual
        if recorded.get(item_id) != actual[item_id]
    )
    missing = sorted(set(actual) - set(recorded))
    add(
        "statuses-agree",
        not disagreements and not missing,
        "every item's status matches the summary" if not (disagreements or missing)
        else "; ".join(disagreements + [f"{i} is absent from the summary" for i in missing]),
    )

    # 2. Every registry entry has a committed test.
    problems = []
    for defect_id, block in sorted(plan.defects.items()):
        node = block.node
        commit = node.get("commit")
        if not commit:
            problems.append(f"{defect_id} names no commit for its red test")
        elif not commit_exists(repo, commit):
            problems.append(f"{defect_id}'s commit {commit} does not resolve in this repository")
        test = node.get("test") or {}
        path = test.get("file")
        if path and not os.path.exists(os.path.join(repo, path)):
            problems.append(f"{defect_id}'s test file {path} does not exist")
    add(
        "registry-tests-committed",
        not problems,
        "every registry entry names a committed test that exists" if not problems
        else "; ".join(problems),
    )

    # 3. Every commit on the branch is named by an item or a decision.
    claimed = {
        block.node.get("commit") for block in plan.items.values()
        if isinstance(block.node.get("commit"), str)
    }
    claimed |= {
        block.node.get("commit") for block in plan.closeouts.values()
        if isinstance(block.node.get("commit"), str)
    }
    base = summary.get("base_commit")
    # A base commit that does not resolve is a different failure from a branch with no commits
    # on it, and `git rev-list` reports them identically — an error and an empty list both come
    # back as nothing. Reading the second as the first would let a run whose history is
    # unreachable pass the check that exists to notice exactly that.
    if base and not commit_exists(repo, base):
        add("commits-name-items", False,
            f"the summary's base commit {short(base)} does not resolve in this repository, so "
            "which commits belong to this run could not be established. Either the record "
            "belongs to a different checkout or the history has been rewritten under it.")
        base = None
    branch_commits = commits_between(repo, base, close_commit or "HEAD") if base else []
    unclaimed = []
    bookkeeping = 0
    for sha in branch_commits:
        if any(sha.startswith(c) or c.startswith(sha[:7]) for c in claimed if c):
            continue
        # A commit touching only the pipeline's own artifacts is bookkeeping, not work, and it
        # needs no item. Stage three commits each item's code and then commits the plan
        # writeback separately, so a run of eight items produces eight commits nothing claims —
        # and reading those as unattributed work would make this check fire on every honest run
        # and be switched off within two of them. What the rule is actually for is code
        # arriving on the branch that no item and no decision accounts for.
        if _only_artifacts(repo, sha):
            bookkeeping += 1
            continue
        subject = git(repo, "log", "-1", "--format=%s", sha).stdout.strip()
        unclaimed.append(f"{short(sha)} {subject}")
    if not summary.get("base_commit"):
        add("commits-name-items", False,
            "the summary records no base commit, so which commits belong to this run could "
            "not be established")
    elif base:
        add(
            "commits-name-items",
            not unclaimed,
            f"all {len(branch_commits)} commit(s) between {short(base)} and "
            f"{short(close_commit) if close_commit else 'HEAD'} are accounted for: "
            f"{len(branch_commits) - bookkeeping} named by an item or a decision, "
            f"{bookkeeping} touching only the pipeline's own artifacts"
            if not unclaimed
            else f"{len(unclaimed)} commit(s) since {short(base)} carry changes that nothing in "
                 "the plan accounts for: " + "; ".join(unclaimed[:8]),
        )

    # 4. Figures the summary could not supply. R-4.1 makes each of these a pipeline finding
    #    rather than something to reconstruct.
    unmeasured = [
        f"{row.get('file')} {row.get('metric')}"
        for row in (summary.get("coverage") or [])
        if row.get("after") is None
    ]
    add(
        "coverage-measured",
        not unmeasured,
        "every declared coverage delta was measured after the run" if not unmeasured
        else f"{len(unmeasured)} delta(s) have no `after` figure: " + ", ".join(unmeasured[:8])
        + ". A delta with no measurement is an item that never ran, which is a different fact "
          "from a target that was missed, and the report states it as the former.",
    )

    # 5. Claim labels, which stage four is entitled to have changed and nothing else is.
    recorded_labels = {}
    for entry in summary.get("claims") or []:
        for claim_id in entry.get("ids") or []:
            recorded_labels[claim_id] = entry.get("label")
    moved = sorted(
        f"{claim_id}: {recorded_labels[claim_id]!r} → {block.node.get('label')!r}"
        for claim_id, block in plan.claims.items()
        if claim_id in recorded_labels and recorded_labels[claim_id] != block.node.get("label")
    )
    add(
        "claim-labels-current",
        True,
        "no claim's label changed after the run summary was written" if not moved
        else "the run record restates these labels as the plan now holds them, which the "
             "close-out gate changed: " + "; ".join(moved)
             + ". The linter's `relabelled-without-closeout` rule is what establishes that a "
               "decision authorised each one.",
    )

    footprint_rows = summary.get("footprint") or []
    completed = {
        item_id for item_id, block in plan.items.items()
        if block.node.get("status") in ("done", "done-with-defect")
    }
    measured_items = {row.get("item") for row in footprint_rows}
    unmeasured_items = sorted(completed - measured_items)
    add(
        "footprint-measured",
        not unmeasured_items,
        f"{len(footprint_rows)} item(s) have a declared-versus-actual footprint diff"
        if not unmeasured_items
        else f"{len(unmeasured_items)} completed item(s) have no footprint measurement: "
             + ", ".join(unmeasured_items),
    )

    return checks


# --------------------------------------------------------------------------------------
# Assembling
# --------------------------------------------------------------------------------------


def read_summary(plan, repo, log_dir):
    """The run summary, from the plan block, falling back to the sidecar copy.

    The block is authoritative: the linter recomputes its item, defect, and dispute lists
    against the plan and fails on a disagreement, so it is the copy that has been checked. The
    sidecar is read only when the block is absent, and its use is recorded.
    """
    if plan.summary_block is not None:
        return planlib.to_plain(plan.summary_block.node), "plan"
    sidecar = os.path.join(repo, log_dir, "run-summary.json")
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as handle:
            return json.load(handle), "sidecar"
    return None, "absent"


def claim_rows(plan):
    """Every claim grouped by its label as the plan now stands, after the close-out gate."""
    by_label = {}
    for claim_id, block in plan.claims.items():
        label = block.node.get("label")
        if isinstance(label, str):
            by_label.setdefault(label, []).append(claim_id)
    return [
        {"label": label, "count": len(ids), "ids": sorted(ids, key=_numeric)}
        for label, ids in sorted(by_label.items())
    ]


def closeout_rows(plan):
    return [
        {
            "id": block.node.get("id"),
            "defect": block.node.get("defect"),
            "option": block.node.get("option"),
            "commit": block.node.get("commit"),
        }
        for _, block in sorted(plan.closeouts.items(), key=lambda kv: _numeric(kv[0]))
    ]


def dispute_decision_rows(plan):
    rows = []
    for block in plan.by_kind.get("dispute-decision", []):
        rows.append({
            "claim": block.node.get("claim"),
            "option": block.node.get("option"),
        })
    rows.sort(key=lambda row: _numeric(row["claim"] or ""))
    return rows


def amendment_flag_rows(plan):
    rows = []
    for _, block in sorted(plan.closeouts.items(), key=lambda kv: _numeric(kv[0])):
        flag = block.node.get("amendment-flag")
        if isinstance(flag, dict):
            rows.append({
                "id": flag.get("id"),
                "document": flag.get("document"),
                "passage": flag.get("passage"),
            })
    return rows


def finding_rows(plan):
    rows = []
    for _, block in sorted(plan.findings.items(), key=lambda kv: _numeric(kv[0])):
        row = {
            "id": block.node.get("id"),
            "category": block.node.get("category"),
            "state": block.node.get("state"),
        }
        if block.node.get("signature"):
            row["signature"] = block.node["signature"]
        rows.append(row)
    return rows


def _numeric(identifier):
    tail = identifier.rstrip("0123456789")
    number = identifier[len(tail):]
    return (tail, int(number) if number else 0)


def ledger_context(repo, ledger_path, close_commit=None):
    """The previous run and the commit distance since it — R-5.6's decay proxy.

    Trust decays as code changes under a static suite, and no run can measure that decay
    directly. What it can measure is how far the code has moved since the last close-out, which
    is why the statement is dated to a commit rather than to a day.

    **The previous run is never this one.** Closing a run appends it to the ledger, so from that
    moment the ledger's latest entry *is* this run — and a re-run of this script would name it
    as its own baseline and report the commits since itself as drift. It did exactly that, and
    what caught it was the report tracer regenerating the skeleton and finding two preamble
    rows that had changed under a finished report. Entries matching this run's close commit are
    skipped, which is correct both before the append and after it.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ledger as ledger_module  # noqa: PLC0415

    full = ledger_path if os.path.isabs(ledger_path) else os.path.join(repo, ledger_path)
    try:
        data = ledger_module.load(full)
    except ledger_module.LedgerError:
        return None, None, None
    if data is None:
        return None, None, None
    previous = None
    for entry in reversed(data.get("runs") or []):
        recorded = entry.get("close_commit") or ""
        if close_commit and recorded and (
            recorded.startswith(close_commit[:7]) or close_commit.startswith(recorded[:7])
        ):
            continue
        previous = entry
        break
    if previous is None:
        return data, None, None
    distance = None
    base = previous.get("close_commit") or previous.get("base_commit")
    if base and commit_exists(repo, base):
        result = git(repo, "rev-list", "--count", f"{base}..HEAD")
        if result.returncode == 0 and result.stdout.strip().isdigit():
            distance = int(result.stdout.strip())
    return data, previous.get("run_id"), distance


def build(plan, repo, log_dir, ledger_path, closed_on, suite_state, report_path):
    summary, source = read_summary(plan, repo, log_dir)

    # **The run's upper boundary is its close commit, not HEAD**, and the difference is the
    # whole reason this is computed before the checks rather than after them. A run covers
    # `base_commit..close_commit`. Once the gate has been held the owner keeps working on the
    # branch — the first thing the `design-os` report told its owner to do was add a line to
    # `.gitignore` — and measuring to HEAD makes every one of those commits look like work no
    # item accounts for. The record would then decay from consistent to inconsistent without
    # anything about the run having changed.
    #
    # Re-deriving `close_commit` as HEAD on a re-run is the same mistake wearing a different
    # hat: it would silently re-date the close every time the record was refreshed. So a record
    # that already carries one keeps it, and only an unclosed run takes HEAD.
    existing = planlib.to_plain(plan.record_block.node) if plan.record_block else {}
    close_commit = existing.get("close_commit")
    if close_commit and not commit_exists(repo, close_commit):
        close_commit = None
    if not close_commit:
        close_commit = git(repo, "rev-parse", "HEAD").stdout.strip() or None

    checks = consistency_checks(plan, summary, repo, close_commit)
    if source == "sidecar":
        checks.insert(1, {
            "check": "run-summary-source",
            "ok": False,
            "detail": (
                "the summary was read from the sidecar copy because the plan carries no "
                "`run-summary` block. The sidecar has not been checked against the plan by "
                "the linter, so every figure taken from it is one degree less verified."
            ),
        })

    summary = summary or {}
    _, baseline_run, distance = ledger_context(repo, ledger_path, close_commit)

    record = {
        "record_version": "1.0",
        "summary_version": summary.get("summary_version") or "1.0",
        "closed": closed_on,
        "close_commit": close_commit,
        "report_path": report_path,
        "plan_path": plan.path,
        "branch": summary.get("branch")
        or git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
        "base_commit": summary.get("base_commit"),
        "started": summary.get("started"),
        "finished": summary.get("finished"),
        "items": summary.get("items") or [],
        # The one section that is recomputed rather than copied forward, and the exception
        # proves the rule. R-4.1 forbids re-deriving a *figure* stage three measured, because a
        # second derivation is a second opinion. A claim's label is not a figure and stage four
        # changes it: a `requirement-wrong` decision relabels a claim `ratified-as-observed`,
        # and the summary was written before the gate was held. Copying it forward would make
        # the report's central table — behavior by authority — describe a state that stopped
        # existing at the close-out. The consistency check below records what moved.
        "claims": claim_rows(plan),
        "defects": summary.get("defects") or [],
        "disputes": summary.get("disputes") or [],
        "coverage": summary.get("coverage") or [],
        "footprint": summary.get("footprint") or [],
        "inherited_failures": summary.get("inherited_failures") or [],
        "narrowings": summary.get("narrowings") or [],
        "decisions": closeout_rows(plan),
        "dispute_decisions": dispute_decision_rows(plan),
        "amendment_flags": amendment_flag_rows(plan),
        "findings": finding_rows(plan),
        "final_suite": suite_state,
        "consistency": checks,
        "baseline_run": baseline_run,
        "commit_distance": distance,
    }
    for key in ("started", "finished"):
        if record[key] is None:
            del record[key]
    return record


# --------------------------------------------------------------------------------------
# The figure set the report tracer checks against
# --------------------------------------------------------------------------------------

def figures(record):
    """Every number the run record computed, as normalised strings.

    This is what makes R-5.1's tracer possible. A number in the report's prose that is not in
    this set is a number nobody computed — and the reason the tracer works at all is that the
    report's tables are filled from this same record, so a prose number should be rare by
    construction rather than merely policed.

    **Only numeric values and the counts derived from them.** An earlier version also scraped
    numerals out of the record's prose fields, and it made the set useless: `WI-05` contributed
    5, `2026-08-01` contributed 2026 and 8 and 1, and a diagnosis mentioning three attempts
    contributed 3. Forty-three figures came out of a record holding perhaps a dozen real ones,
    and an invented number had better than even odds of matching one by accident. A figure that
    exists only inside a quoted sentence is not this stage's figure; the sentence is quoted
    verbatim in a generated table, and quoting the sentence is how the report should state it.

    Percentages appear in three forms because a writer legitimately writes any of them: 78.89,
    78.9, and 79. All three are admitted for a figure the record holds, and nothing else is.
    """
    found = set()

    def walk(value):
        if isinstance(value, bool) or isinstance(value, str) or value is None:
            return
        if isinstance(value, (int, float)):
            _add_number(found, value)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            # A list's own length is a figure the report will state — "six items are done" —
            # and it is derived from the record rather than being written in it.
            _add_number(found, len(value))

    walk(record)

    # Counts the report states that are lengths of things rather than fields. Each is derivable
    # from the record by anybody, which is exactly why it belongs in the traceable set.
    for entry in record.get("items") or []:
        _add_number(found, entry.get("count"))
    for entry in record.get("claims") or []:
        _add_number(found, entry.get("count"))
    coverage = record.get("coverage") or []
    _add_number(found, sum(1 for row in coverage if row.get("met")))
    _add_number(found, sum(1 for row in coverage if not row.get("met")))
    footprint = record.get("footprint") or []
    _add_number(found, sum(
        1 for row in footprint
        if not row.get("declared_only") and not row.get("actual_only")
    ))
    items = {entry.get("status"): entry.get("count", 0) for entry in record.get("items") or []}
    _add_number(found, sum(items.values()))
    _add_number(found, items.get("done", 0) + items.get("done-with-defect", 0))
    claims = {entry.get("label"): entry.get("count", 0) for entry in record.get("claims") or []}
    _add_number(found, sum(claims.values()))
    _add_number(found, claims.get("cited", 0) + claims.get("ratified", 0)
                + claims.get("ratified-as-observed", 0))
    return found


def _add_number(found, value):
    if value is None or isinstance(value, bool):
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        return
    found.add(_normalise(number))
    found.add(_normalise(round(number, 1)))
    found.add(_normalise(round(number)))


def _normalise(number):
    number = float(number)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def render_consistency(checks):
    lines = []
    for check in checks:
        mark = "ok  " if check["ok"] else "FAIL"
        lines.append(f"  {mark} {check['check']}")
        lines.append(f"       {check['detail']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--assessment")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--date", help="the close-out date; defaults to today")
    parser.add_argument("--phase", default="executed", choices=("executed", "closed"),
                        help="`executed` while assembling before the gate, `closed` after it")
    parser.add_argument("--suite-command", help="override the suite command")
    parser.add_argument("--no-suite", action="store_true",
                        help="do not run the suite; the record says it was not measured")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--write", action="store_true",
                        help="write the run-record block into the plan and a JSON sidecar")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    planio = siblings.planio()
    plan = planio.Plan(
        args.plan, assessment=args.assessment, phase=args.phase, lint_writes=args.write
    )

    if args.no_suite:
        suite_state = dict(UNMEASURED_SUITE)
        suite_state["note"] = "--no-suite was passed, so the suite was not run"
    else:
        suite_state = final_suite(
            plan, args.repo, args.log_dir, args.timeout, args.suite_command
        )

    closed_on = args.date
    if not closed_on:
        import datetime  # noqa: PLC0415

        closed_on = datetime.date.today().isoformat()

    record = build(
        plan, args.repo, args.log_dir, args.ledger, closed_on, suite_state, args.report
    )

    if args.write:
        try:
            changed = plan.upsert_block(
                planio.RECORD_SECTION, "run-record", record, {}, intro=RECORD_INTRO,
            )
        except planio.WriteRejected as rejected:
            print(str(rejected), file=sys.stderr)
            return 1
        target_dir = os.path.join(args.repo, args.log_dir)
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, "run-record.json"), "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"{'wrote' if changed else 'unchanged'}: the run record in {args.plan}")
        print(f"  and a copy at {os.path.join(args.log_dir, 'run-record.json')}")

    if args.json:
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0

    failed = [check for check in record["consistency"] if not check["ok"]]
    print(f"{args.plan} — run record for {record['branch']} closed {record['closed']}")
    print(f"  items: " + ", ".join(
        f"{entry['count']} {entry['status']}" for entry in record["items"]
    ) or "  items: none")
    print(f"  defects: {', '.join(record['defects']) or 'none'}"
          f"   decisions: {len(record['decisions'])}")
    print(f"  disputes: {', '.join(record['disputes']) or 'none'}")
    suite_note = record["final_suite"]
    if suite_note.get("measured"):
        print(f"  suite: {suite_note['passed']} passed, {suite_note['failed']} failed"
              + (f" ({len(suite_note['expected_failures'])} expected)"
                 if suite_note["expected_failures"] else ""))
    else:
        print(f"  suite: not measured — {suite_note.get('note', '')}")
    print(f"  R-4.2 consistency: {len(record['consistency']) - len(failed)} of "
          f"{len(record['consistency'])} checks passed")
    print(render_consistency(record["consistency"]))
    if failed:
        print(f"\n  {len(failed)} consistency check(s) failed. R-4.2 makes each one a pipeline "
              "finding and degrades the report's stated confidence. Run findings.py next; do "
              "not repair the summary by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

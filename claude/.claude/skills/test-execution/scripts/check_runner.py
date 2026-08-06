#!/usr/bin/env python3
"""Run an item's completion checks and report pass or fail per check. R-5.4 to R-5.6.

**The executor never grades its own checks.** That is what this script is for, and it is the
reason it is a script rather than instructions: an agent that decides whether its own work
passed will decide generously, not from bad faith but because it knows what it meant.

Eight kinds run here. Five are authored by the plan — `file-exists`, `tests-pass`,
`guard-holds`, `mutation`, `pattern-count` — and three are implied, generated from the item
rather than written on it:

* **`coverage-delta`**, one per entry in the item's own field. There is deliberately no such
  check kind, because two copies of one statement drift and did.
* **`claim-annotations`**, generated from the item's `claims` list (R-5.7).
* **`standing-invariant`**, which runs on every item whether it asks for one or not (R-5.4):
  the whole suite green except the defect registry and the failures pre-flight recorded.

## The mutation protocol

R-5.6 states it and this implements it exactly, with one refinement recorded below. It is the
only check that modifies production code.

The step this script cannot do is apply the edit: `mutation` is prose — "delete the filter at
line 476" — and reading it is model work. So the model prepares the mutated file **outside the
repository** and passes it in with `--mutated-file`. Everything from that point is one
process: back up, copy in, run, classify, restore, verify, re-run. That is what R-5.6 means by
never delegating a mutation to a subagent — whoever writes into the repository controls the
restore, in the same process, in a `finally`.

**Refinement to R-5.6's restore step, and the reason for it.** R-5.6 says restore via the
named restore command and verify the tree is byte-identical two ways. Every restore command
real plans write is `git checkout -- <file>`, and that is wrong whenever the item has
legitimately modified the file and not yet committed it — a seam item is exactly that case,
and `git checkout --` would silently destroy its work. So this restores from its own backup as
the ground truth, runs the named restore command as R-5.6 requires, and **fails the check when
the named command did not by itself produce a byte-identical file**, recording why. The tree is
safe either way and the deviation is reported rather than hidden.

The two verifications become: a byte comparison against the backup, and the file's git status
matching what it was *before* the mutation rather than being empty. "Empty" is only right for
an item that has not touched the file, which is not the interesting case.

**Crash safety.** A protocol that only restores on the happy path is worse than none, because
it teaches people to trust it. Before the mutated content is written, a recovery record goes
to the sidecar naming the backup and its target. Interrupt signals restore and re-raise. And
`--recover`, which every run performs at startup, restores from a record left by a process
that was killed outright.

Usage:
    python3 check_runner.py <plan> --item WI-04 --repo . --json
    python3 check_runner.py <plan> --item WI-06 --mutation-check 3 \\
            --mutated-file $SCRATCH/report.py.mutated --json
    python3 check_runner.py <plan> --recover --repo .
"""

import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claim_annotations  # noqa: E402
import planio  # noqa: E402
import siblings  # noqa: E402
import suite  # noqa: E402

DEFAULT_LOG_DIR = "docs/test-execution-log"
RECOVERY_FILE = ".mutation-in-progress.json"


# --------------------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------------------


def record(kind, outcome, detail=None, claim=None, log=None, **extra):
    """One entry in the shape `actuals.checks` expects, so results are written back as read."""
    entry = {"kind": kind, "outcome": outcome}
    if claim:
        entry["claim"] = claim
    if detail:
        entry["detail"] = detail
    if log:
        entry["log"] = log
    entry.update(extra)
    return entry


def _digest(text):
    """A short, stable name for a command, so a repeated run writes the same file names.

    `hash()` on a string is salted per process in CPython, so two identical runs produced log
    files with different names and a plan whose only differences from the previous run's were
    those names. A record you cannot diff against the previous one is most of the value of
    keeping a record.
    """
    import hashlib  # noqa: PLC0415

    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def write_log(repo, log_dir, name, text):
    """Bulk output goes to the sidecar and the plan references it by path (R-9.2)."""
    directory = os.path.join(repo, log_dir)
    os.makedirs(directory, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    relative = os.path.join(log_dir, safe)
    with open(os.path.join(repo, relative), "w", encoding="utf-8") as handle:
        handle.write(text)
    return relative


# --------------------------------------------------------------------------------------
# The five authored kinds
# --------------------------------------------------------------------------------------


def check_file_exists(check, repo):
    path = check.get("path")
    absent = check.get("absent") is True
    exists = os.path.exists(os.path.join(repo, path))
    if absent:
        return record(
            "file-exists",
            "passed" if not exists else "failed",
            None if not exists else f"{path} still exists and this check requires its absence",
        )
    return record(
        "file-exists",
        "passed" if exists else "failed",
        None if exists else f"{path} does not exist",
    )


def check_tests_pass(check, repo, log_dir, timeout, kind="tests-pass", allowed=()):
    """The named command exits zero, and every named test appears in its output.

    `allowed` is the tests that are permitted to be red: the defect registry's, and the
    failures pre-flight recorded. **Without it, R-7.2 is unusable.** The moment a defect's red
    test is committed — which R-7.2 requires — every later item carrying a whole-suite
    `tests-pass` check fails, and the plan collapses one item after another over a failure the
    owner has already been told about and asked to decide on. The check asks whether the tests
    pass; a test standing red under a recorded, owner-facing decision is not this item's
    failure, and the detail says which ones were tolerated so nobody has to guess.
    """
    command = check.get("command")
    expect = check.get("expect", "all-pass")
    named = [t for t in (check.get("tests") or []) if isinstance(t, str)]
    result = suite.run(command, repo, timeout)
    failures, basis = suite.failing_tests(result.output)
    log = write_log(repo, log_dir, f"{kind}-{_digest(command)}.txt",
                    f"$ {command}\n\n{result.output}")

    if result.timed_out:
        return record(kind, "not-run", f"`{command}` timed out after {timeout}s", log=log)

    if expect == "named-tests-fail":
        if result.ok:
            return record(kind, "failed",
                          f"`{command}` exited zero and this check expects the named tests to "
                          "fail", log=log)
        unfailed = [name for name in named if not suite.names_match(name, failures)]
        if unfailed:
            return record(
                kind, "failed",
                f"the command failed but these named test(s) did not: {', '.join(unfailed)}. "
                f"Observed failures: {', '.join(failures) or 'none could be parsed'}",
                log=log,
            )
        return record(kind, "passed", f"{len(named)} named test(s) failed as required", log=log)

    if not result.ok:
        tolerated = [name for name in failures if _is_allowed(name, allowed)]
        unexpected = [name for name in failures if name not in tolerated]
        if failures and not unexpected:
            return record(
                kind, "passed",
                f"`{command}` exited {result.returncode}, and every failure is a test that is "
                f"allowed to be red: {', '.join(tolerated[:12])}. Those are the defect "
                "registry's committed red tests and the failures pre-flight recorded. Nothing "
                "this item did is among them.",
                log=log,
            )
        return record(
            kind, "failed",
            f"`{command}` exited {result.returncode}. "
            + (f"Failing: {', '.join(unexpected[:12])}" if unexpected
               else "No recognised reporter format in the output; see the log.")
            + (f" ({len(tolerated)} further failure(s) were registry or inherited tests and "
               "are not counted against this item.)" if tolerated else ""),
            log=log,
        )

    if not named:
        return record(kind, "passed", log=log)

    # R-10.2: the check is that the named tests ran. When the reporter did not name them,
    # that is unknown rather than true, and unknown is reported as not-run.
    unseen = [name for name in named if not _mentions(result.output, name)]
    if unseen:
        return record(
            kind, "not-run",
            f"`{command}` exited zero, but its output does not name {len(unseen)} of the "
            f"test(s) this check requires to have run: {', '.join(unseen)}. A passing run of "
            "zero tests satisfies an exit code, which is what naming tests exists to prevent, "
            "so this is reported as not-run rather than passed. Give the command a reporter "
            "that prints test names — `-v` for pytest, `--reporter=verbose` for vitest — in "
            "the plan, not here: editing a check is forbidden (R-2.3).",
            log=log,
        )
    return record(kind, "passed", f"exit zero with {len(named)} named test(s) present", log=log)


def _mentions(output, name):
    """Whether the run's output names this test, in whatever separator style it uses."""
    return suite.mentioned_in(output, name)


def _is_allowed(name, allowed):
    return any(
        suite.names_match(permitted, [name]) or suite.names_match(name, [permitted])
        for permitted in allowed
    )


def check_guard_holds(check, repo, log_dir, timeout, allowed=()):
    result = check_tests_pass(
        {"command": check.get("command"), "expect": "all-pass"},
        repo, log_dir, timeout, kind="guard-holds", allowed=allowed,
    )
    if result["outcome"] == "failed":
        result["detail"] = (
            f"the characterization tests guarding this seam no longer pass, so the "
            f"refactoring changed behavior. R-6.3: revert the seam immediately, preserve the "
            f"failing diff on a side branch, and fail the item. A behavior-changing "
            f"refactoring is never committed and this is not a candidate for "
            f"retry-until-green. "
        ) + (result.get("detail") or "")
    return result


def check_pattern_count(check, repo):
    pattern = check.get("pattern")
    expect = check.get("expect")
    comparison = check.get("comparison", "exactly")
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as error:
        return record("pattern-count", "not-run", f"the pattern is not a valid regex: {error}")

    total = 0
    scanned = []
    for entry in check.get("scope") or []:
        matched = glob.glob(os.path.join(repo, entry), recursive=True)
        files = []
        for path in sorted(matched):
            if os.path.isfile(path):
                files.append(path)
            elif os.path.isdir(path):
                # A directory in scope means every file under it. Plans write `scope: [tests]`
                # for a removal check that must hold across a whole tree — "the placeholders
                # are gone from the test suite", not "gone from this one file" — and treating
                # a directory as zero files would pass that check by scanning nothing.
                for root, directories, names in os.walk(path):
                    directories[:] = [d for d in directories
                                      if d not in _CACHE_SKIP and d not in _CACHE_DIRS]
                    files.extend(os.path.join(root, name) for name in sorted(names))
        for path in sorted(set(files)):
            scanned.append(os.path.relpath(path, repo))
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    total += len(compiled.findall(handle.read()))
            except OSError:
                continue

    ok = {
        "exactly": total == expect,
        "at-least": total >= expect,
        "at-most": total <= expect,
    }.get(comparison, total == expect)

    detail = (
        f"{total} match(es) across {len(scanned)} file(s), required {comparison} {expect}"
        + ("; no file in the scope exists" if not scanned else "")
    )
    if not scanned and expect == 0:
        # Zero matches across zero files is not evidence of removal. This is the shape a
        # `pattern-count: 0` check takes when the scope path is wrong, and it would otherwise
        # pass for exactly the wrong reason.
        return record("pattern-count", "not-run",
                      f"no file in the scope exists, so a count of zero says nothing about "
                      f"whether the pattern was removed. Scope: {check.get('scope')}")
    return record("pattern-count", "passed" if ok else "failed", detail)


# --------------------------------------------------------------------------------------
# The mutation protocol (R-5.6)
# --------------------------------------------------------------------------------------


# Directories a cache invalidation must not descend into: the repository's own history, and
# the vendored trees where a sweep would cost seconds and find nothing that matters.
_CACHE_SKIP = {".git", "node_modules", ".venv", "venv", "env", ".tox", "dist", "build"}
_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def invalidate_caches(repo):
    """Delete compiled-bytecode and runner caches under the repository.

    **This is not housekeeping. Without it the mutation protocol reports fiction**, and it
    took a real run to find out.

    CPython records the source file's modification time, to a whole second, in the header of
    the `.pyc` it compiles. A mutation applied and then restored inside the same second
    produces a source file whose recorded time and size are unchanged — the C8 case that
    exposed this changed one `+` to a `-`, so the size was identical — and the interpreter
    reuses the stale bytecode. The observed result was a file verified byte-identical to its
    backup by two independent checks, and a test run that still behaved as though the mutation
    were in place.

    That is the worst shape a failure here can take: every verification R-5.6 asks for passes
    and the answer is still wrong. So the caches go, after the mutation is applied and after
    every restore. It is a no-op in ecosystems that do not cache this way, and it costs
    milliseconds on a repository of any size that keeps its dependencies out of the tree.

    Returns the directories removed, so the mutation transcript can say what it cleared.
    """
    removed = []
    for root, directories, _ in os.walk(repo):
        directories[:] = [d for d in directories if d not in _CACHE_SKIP]
        for name in list(directories):
            if name in _CACHE_DIRS:
                path = os.path.join(root, name)
                shutil.rmtree(path, ignore_errors=True)
                removed.append(os.path.relpath(path, repo))
                directories.remove(name)
    return removed


class MutationGuard:
    """Backup, mutate, and restore, in one process, with a record left on disk.

    Everything about this class is about the restore. The mutation is trivial; leaving a
    repository modified because a test runner crashed is not.
    """

    def __init__(self, repo, target, log_dir):
        self.repo = repo
        self.relative = target
        self.path = os.path.join(repo, target)
        self.log_dir = log_dir
        self.backup_dir = None
        self.backup = None
        self.git_status_before = None
        self.installed = []

    # -- context management ---------------------------------------------------------

    def __enter__(self):
        # Outside the repository, so no repository operation — a checkout, a clean, a reset —
        # can reach the only copy of the original.
        self.backup_dir = tempfile.mkdtemp(prefix="mutation-backup-")
        self.backup = os.path.join(self.backup_dir, os.path.basename(self.path))
        shutil.copy2(self.path, self.backup)
        self.git_status_before = self._git_status()
        self._write_recovery()
        self._install_handlers()
        return self

    def __exit__(self, *_):
        try:
            self.restore_from_backup()
        finally:
            self._remove_recovery()
            self._remove_handlers()
            if self.backup_dir:
                shutil.rmtree(self.backup_dir, ignore_errors=True)
        return False

    # -- the protocol ---------------------------------------------------------------

    def apply(self, mutated_file):
        shutil.copyfile(mutated_file, self.path)
        return invalidate_caches(self.repo)

    def named_restore(self, command, timeout=120):
        """Run the plan's own restore command, as R-5.6 requires."""
        return suite.run(command, self.repo, timeout)

    def matches_backup(self):
        with open(self.backup, "rb") as a, open(self.path, "rb") as b:
            return a.read() == b.read()

    def git_status_unchanged(self):
        """The second verification, corrected.

        R-5.6 asks for a clean `git status`, which is right only for a file the item has not
        touched. An item that has legitimately modified this file and not yet committed it —
        a seam item, always — has a dirty status before the mutation and must have the same
        dirty status after it. What is verified is that nothing changed, not that nothing is
        there.
        """
        return self._git_status() == self.git_status_before

    def restore_from_backup(self):
        if self.backup and os.path.exists(self.backup) and os.path.exists(os.path.dirname(self.path)):
            shutil.copyfile(self.backup, self.path)
            invalidate_caches(self.repo)

    def _git_status(self):
        completed = subprocess.run(
            ["git", "status", "--porcelain", "--", self.relative],
            cwd=self.repo, capture_output=True, text=True,
        )
        return completed.stdout.strip()

    # -- crash safety ----------------------------------------------------------------

    def _recovery_path(self):
        return os.path.join(self.repo, self.log_dir, RECOVERY_FILE)

    def _write_recovery(self):
        os.makedirs(os.path.join(self.repo, self.log_dir), exist_ok=True)
        with open(self._recovery_path(), "w", encoding="utf-8") as handle:
            json.dump(
                {"target": self.relative, "backup": self.backup,
                 "git_status_before": self.git_status_before},
                handle, indent=2,
            )

    def _remove_recovery(self):
        try:
            os.remove(self._recovery_path())
        except OSError:
            pass

    def _install_handlers(self):
        def handler(signum, _frame):
            self.restore_from_backup()
            self._remove_recovery()
            self._remove_handlers()
            os.kill(os.getpid(), signum)

        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                previous = signal.signal(number, handler)
            except (ValueError, OSError):
                continue
            self.installed.append((number, previous))

    def _remove_handlers(self):
        for number, previous in self.installed:
            try:
                signal.signal(number, previous)
            except (ValueError, OSError):
                pass
        self.installed = []


def recover(repo, log_dir):
    """Restore from a record a killed process left behind. Run at every startup.

    A SIGKILL cannot be caught, so the in-process restore is not enough on its own. What is
    left is the record, and this is what reads it.
    """
    path = os.path.join(repo, log_dir, RECOVERY_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        left = json.load(handle)

    target = os.path.join(repo, left.get("target", ""))
    backup = left.get("backup")
    report = {"target": left.get("target"), "backup": backup}

    if backup and os.path.exists(backup) and os.path.exists(target):
        with open(backup, "rb") as a, open(target, "rb") as b:
            already = a.read() == b.read()
        if not already:
            shutil.copyfile(backup, target)
        report["restored"] = not already
        report["outcome"] = "restored from the backup" if not already else (
            "already matched the backup; nothing to restore"
        )
        shutil.rmtree(os.path.dirname(backup), ignore_errors=True)
    else:
        report["restored"] = False
        report["outcome"] = (
            "THE BACKUP IS GONE. A mutation was in progress when a previous run died and its "
            f"backup of {left.get('target')} is no longer on disk — temporary directories do "
            "not survive a reboot. Restore the file from git yourself, check the diff first "
            "in case the item had uncommitted work in it, and do not trust this run's "
            "mutation results until you have."
        )
    os.remove(path)
    return report


def check_mutation(check, repo, log_dir, timeout, mutated_file):
    """R-5.6, in order, with every deviation failing the check."""
    claim = check.get("claim")
    target = check.get("file")
    command = check.get("command")
    restore_command = check.get("restore")
    named = [t for t in (check.get("tests") or []) if isinstance(t, str)]

    if not os.path.exists(os.path.join(repo, target)):
        return record("mutation", "not-run", f"{target} does not exist", claim=claim)
    if not mutated_file:
        return record(
            "mutation", "not-run",
            f"no mutated file was supplied for {target}. The edit is prose — "
            f"\"{(check.get('mutation') or '')[:120]}\" — and reading it is model work. "
            "Prepare the mutated content outside the repository and pass it with "
            "--mutated-file; everything after that is one process, so the restore is "
            "controlled by whoever made the change (R-5.6).",
            claim=claim,
        )
    if not os.path.exists(mutated_file):
        return record("mutation", "not-run",
                      f"the supplied mutated file {mutated_file} does not exist", claim=claim)

    transcript = [f"# mutation check for {claim} on {target}",
                  f"# {check.get('mutation')}", ""]
    deviations = []

    with MutationGuard(repo, target, log_dir) as guard:
        with open(guard.path, "rb") as a, open(mutated_file, "rb") as b:
            if a.read() == b.read():
                return record(
                    "mutation", "not-run",
                    "the supplied mutated file is identical to the file in the repository, so "
                    "no mutation would be applied and the check would pass or fail for "
                    "reasons unrelated to the edit. Apply the named edit to the copy first.",
                    claim=claim,
                )

        # Run the command **before** mutating, and this costs a third run of the command for
        # a reason worth the cost. R-5.6's last step is "rerun green", which reads as absolute
        # green and is wrong: a suite with an inherited failure, a registry test standing red,
        # or a dispute in it is never absolutely green, and holding the restore to that
        # standard fails every mutation check downstream of the first honest red. What the
        # step is really for is proving the restore restored, and the precise form of that is
        # "the same tests fail afterwards as before".
        #
        # The pre-run also answers a question nothing else asks: whether the named test was
        # already failing. A test that fails before the edit and after it has not been shown
        # to detect anything, which is R-7.4's reasoning applied to a test that is broken
        # rather than to one that is registered.
        before = suite.run(command, repo, timeout)
        before_failures, _ = suite.failing_tests(before.output)
        transcript.append(f"$ {command}   # before the mutation")
        transcript.append(before.output)

        already_failing = [n for n in named if suite.names_match(n, before_failures)]
        if already_failing:
            return record(
                "mutation", "not-run",
                f"the named test(s) {', '.join(already_failing)} were already failing before "
                "the mutation was applied, so their failure under it proves nothing about "
                "whether the suite can detect this defect. Nothing was mutated. Fix or "
                "register the failing test first: if its claim is cited or ratified this is a "
                "defect and the check is suspended under R-7.4, and if its claim is pinned "
                "this is a dispute and the item fails.",
                claim=claim, log=write_log(
                    repo, log_dir, f"mutation-{claim}-{os.path.basename(target)}.txt",
                    "\n".join(transcript)),
            )

        applied_clear = guard.apply(mutated_file)
        transcript.append(
            f"# cleared {len(applied_clear)} cache director(y/ies) after applying the "
            "mutation: " + (", ".join(applied_clear) if applied_clear else "none present")
        )
        transcript.append(f"$ {command}")
        result = suite.run(command, repo, timeout)
        transcript.append(result.output)

        failures, basis = suite.failing_tests(result.output)
        verdict, reason = suite.classify_failure(result.output, len(named) or 1, len(failures))

        # Restore before judging anything, so a judgement that raises cannot skip it. The
        # context manager restores from the backup again on the way out; both are cheap and
        # the second is what makes the first optional rather than load-bearing.
        restored = guard.named_restore(restore_command) if restore_command else None
        cleared = invalidate_caches(repo)
        named_restore_worked = guard.matches_backup()
        if not named_restore_worked:
            deviations.append(
                f"the named restore command `{restore_command}` did not put {target} back: "
                "the file still differs from the pre-mutation backup. This is what happens "
                "when the restore is `git checkout -- <file>` and the item has legitimately "
                "modified that file without committing it yet, which is every seam item. The "
                "backup has been restored, so nothing is lost, and the check fails because "
                "R-5.6 makes any deviation from the protocol a failure. Fix the restore "
                "command in the plan."
            )
            guard.restore_from_backup()
        if restored is not None and restored.returncode not in (0, None):
            deviations.append(
                f"the named restore command exited {restored.returncode}: "
                f"{restored.output.strip()[:300]}"
            )
        if not guard.matches_backup():
            deviations.append(
                f"{target} does not match its pre-mutation backup even after restoring from "
                "it. The working tree may be left modified; check it by hand before trusting "
                "anything else in this run."
            )
        if not guard.git_status_unchanged():
            deviations.append(
                f"the git status of {target} changed across the mutation: it was "
                f"{guard.git_status_before!r} before and is {guard._git_status()!r} now"
            )

        transcript.append(f"\n$ {restore_command}")
        transcript.append(restored.output if restored is not None else "(no restore command)")
        transcript.append(
            f"# cleared {len(cleared)} cache director(y/ies) after the restore: "
            + (", ".join(cleared) if cleared else "none present")
        )

        rerun = suite.run(command, repo, timeout)
        transcript.append(f"\n$ {command}   # after restore")
        transcript.append(rerun.output)

    log = write_log(repo, log_dir, f"mutation-{claim}-{os.path.basename(target)}.txt",
                    "\n".join(transcript))

    if deviations:
        return record("mutation", "failed", " ".join(deviations), claim=claim, log=log)

    if result.timed_out:
        return record("mutation", "not-run",
                      f"the mutated run timed out after {timeout}s", claim=claim, log=log)

    if result.ok:
        return record(
            "mutation", "failed",
            f"the named edit was applied and `{command}` still exited zero, so the suite "
            f"cannot detect this defect. {claim} is asserted by a test that has not been "
            "shown to be able to fail. Do not edit the check or loosen anything to make this "
            "pass (R-2.3): either the assertion is not reaching the behavior the claim "
            "describes, or the claim describes something the code discards before any test "
            "can see it — and the second is a planning defect worth reporting.",
            claim=claim, log=log,
        )

    unfailed = [name for name in named if not suite.names_match(name, failures)]
    if unfailed:
        return record(
            "mutation", "failed",
            f"the mutation made the run fail, but not through the named test(s): "
            f"{', '.join(unfailed)} did not fail. Observed: "
            f"{', '.join(failures[:10]) or 'no failures could be parsed from the output'}. A "
            "mutation that makes some test fail somewhere proves less than one that makes the "
            "intended test fail.",
            claim=claim, log=log,
        )

    if verdict == "error":
        return record(
            "mutation", "failed",
            f"the named test(s) failed, but by error rather than by assertion: {reason}. R-5.6 "
            "requires the distinction, because a test that errors under mutation proves it "
            "reaches the code and proves nothing about what it asserts. Deleting a function so "
            "that every test importing it explodes would otherwise satisfy every mutation "
            "check in the plan at once. Make the edit smaller and behavioral.",
            claim=claim, log=log,
        )
    if verdict == "unknown":
        return record(
            "mutation", "not-run",
            f"the named test(s) failed and whether they failed by assertion could not be read "
            f"from the output: {reason}. R-10.2 forbids inferring a check outcome, so this is "
            "reported as not-run rather than guessed at. Run the command by hand and look.",
            claim=claim, log=log,
        )

    rerun_failures, _ = suite.failing_tests(rerun.output)
    if set(rerun_failures) != set(before_failures):
        appeared = sorted(set(rerun_failures) - set(before_failures))
        vanished = sorted(set(before_failures) - set(rerun_failures))
        return record(
            "mutation", "failed",
            "after the restore the command does not behave as it did before the mutation"
            + (f". Newly failing: {', '.join(appeared[:8])}" if appeared else "")
            + (f". No longer failing: {', '.join(vanished[:8])}" if vanished else "")
            + ". The file was verified byte-identical to its backup, so something outside "
            "it — a cache, a generated artefact, a fixture written during the run — did not "
            "come back with it. The mutation result cannot be trusted until that is "
            "understood.",
            claim=claim, log=log,
        )

    return record(
        "mutation", "passed",
        f"the named edit made {len(named)} named test(s) fail by assertion ({reason}), the "
        "file was restored and verified byte-identical against its backup with an unchanged "
        "git status, and the suite is green again.",
        claim=claim, log=log,
    )


# --------------------------------------------------------------------------------------
# The three implied checks
# --------------------------------------------------------------------------------------


def coverage_source(plan):
    """The coverage command and report path, taken from slice zero rather than guessed."""
    zero = plan.slices.get("S0")
    command = report = None
    if zero is not None:
        for item_id in zero.node.get("items") or []:
            item = plan.items.get(item_id)
            if item is None:
                continue
            for check in item.node.get("completion-checks") or []:
                if not isinstance(check, dict):
                    continue
                if check.get("kind") == "tests-pass" and command is None:
                    command = check.get("command")
                if check.get("kind") == "file-exists" and report is None and not check.get("absent"):
                    report = check.get("path")
    return command, report


def measure_coverage(repo, command, report, timeout):
    """Run the coverage command and parse the report it produced.

    Imported from the assessment skill rather than reimplemented. That parser handles five
    formats and this suite has twice been bitten by two copies of one statement drifting
    apart; a second coverage parser would be the third time.
    """
    from pathlib import Path  # noqa: PLC0415

    parse = siblings.parse_coverage()
    if not command or not report:
        return None, (
            "the plan does not say how to produce a coverage report: slice zero carries no "
            "`tests-pass` command paired with a `file-exists` naming the report. Pass "
            "--coverage-command and --coverage-report."
        )
    result = suite.run(command, repo, timeout)
    full = Path(os.path.join(repo, report))
    if not full.is_file():
        return None, (
            f"`{command}` did not produce {report} (exit {result.returncode}), so no coverage "
            "figure exists to compare against."
        )
    fmt = parse.sniff(full)
    if fmt == "unknown":
        return None, (
            f"{report} is in no format the assessment stage's parser recognises. It handles "
            "coverage.py JSON, Cobertura XML, LCOV, Istanbul JSON, and Go profiles. This is "
            "reported rather than guessed at."
        )
    try:
        parsed = parse.PARSERS[fmt](full)
    except Exception as error:  # noqa: BLE001 — any parse failure is reported, not inferred
        return None, f"{report} ({fmt}) could not be parsed: {error}"
    return parsed, None


# The plan's four metric names against the parser's per-file keys. `statements` maps to the
# line percentage because that is what coverage.py's statement count is; saying so here is
# better than letting the two vocabularies quietly disagree.
_METRIC_KEYS = {"lines": "line_pct", "statements": "line_pct", "branches": "branch_pct"}


def _file_metric(parsed, path, metric):
    """One file's percentage for one metric, or None when it is not measurable.

    Function coverage is derived rather than read: the parser reports a line percentage per
    function, and the share of functions with any coverage at all is what `functions` means
    in a plan. Stating the derivation matters — a figure whose definition is unstated is a
    figure two people will compute differently.
    """
    for entry in parsed.get("files") or []:
        name = entry.get("path")
        if not isinstance(name, str):
            continue
        if not (name == path or name.endswith("/" + path) or path.endswith("/" + name)):
            continue
        key = _METRIC_KEYS.get(metric)
        if key:
            value = entry.get(key)
            return float(value) if isinstance(value, (int, float)) else None
        if metric == "functions":
            functions = entry.get("functions") or []
            if not functions:
                return None
            covered = sum(
                1 for f in functions
                if isinstance(f.get("line_pct"), (int, float)) and f["line_pct"] > 0
            )
            return 100.0 * covered / len(functions)
        return None
    return None


BASELINE_FILE = "coverage-baseline.json"


def load_baseline(repo, log_dir):
    """Slice zero's recorded coverage figures, which every delta is measured against (R-5.5)."""
    path = os.path.join(repo, log_dir, BASELINE_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("files") or {}


def record_baseline(repo, log_dir, command, report, timeout):
    """Write the baseline. Run once, immediately after slice zero completes.

    Not at pre-flight, and the difference is the whole reason slice zero exists: slice zero
    rewrites the coverage configuration, so a figure measured before it ran is against a
    denominator that is about to stop existing. `baseline-source: slice-zero` is the usual
    answer in a plan precisely because this is when the number becomes real.
    """
    parsed, problem = measure_coverage(repo, command, report, timeout)
    if parsed is None:
        return {"error": problem}
    files = {}
    root = os.path.abspath(repo)
    for entry in parsed.get("files") or []:
        name = entry.get("path")
        if not isinstance(name, str):
            continue
        # Keyed by a repository-relative path, always. Istanbul writes absolute paths and
        # coverage.py writes relative ones, and a plan's `coverage-delta` names the relative
        # form — so a baseline keyed by whatever the tool happened to emit is a baseline no
        # delta can look itself up in. On this repository every figure was zero, so the
        # mismatch would have gone unnoticed until the first run where the baseline mattered.
        relative = os.path.relpath(name, root) if os.path.isabs(name) else name
        for metric in ("lines", "branches", "functions", "statements"):
            value = _file_metric(parsed, name, metric)
            if value is not None:
                files[f"{relative}:{metric}"] = round(value, 2)
    payload = {"command": command, "report": report, "format": parsed.get("format"),
               "files": files}
    os.makedirs(os.path.join(repo, log_dir), exist_ok=True)
    with open(os.path.join(repo, log_dir, BASELINE_FILE), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return payload


def check_coverage_deltas(item, plan, repo, log_dir, coverage_command, coverage_report,
                          baseline, timeout):
    """Every `coverage-delta` entry is an implied completion check (R-5.5)."""
    deltas = [d for d in (item.get("coverage-delta") or []) if isinstance(d, dict)]
    if not deltas:
        return []

    parsed, problem = measure_coverage(repo, coverage_command, coverage_report, timeout)
    if parsed is None:
        return [
            record("coverage-delta", "not-run", problem, file=d.get("file"),
                   metric=d.get("metric"))
            for d in deltas
        ]

    results = []
    for delta in deltas:
        path, metric = delta.get("file"), delta.get("metric")
        wanted = delta.get("to")
        after = _file_metric(parsed, path, metric)
        source = delta.get("baseline-source")
        before = {
            "none": 0.0,
            "slice-zero": (baseline or {}).get(f"{path}:{metric}"),
        }.get(source, delta.get("from"))
        if source == "assessment-index":
            before = delta.get("from")

        if after is None:
            results.append(record(
                "coverage-delta", "not-run",
                f"{path} does not appear in {coverage_report}, so its {metric} coverage could "
                "not be measured. A file the report does not mention is not a file at zero.",
                file=path, metric=metric,
            ))
            continue

        passed = after >= wanted
        results.append(record(
            "coverage-delta", "passed" if passed else "failed",
            f"{path} {metric}: {after:.1f}% measured, {wanted}% required"
            + (f", from a recorded baseline of {before:.1f}%" if isinstance(before, (int, float))
               else f", with no recorded baseline (source `{source}`)")
            + ("" if passed else
               ". The item's tests do not reach as much of this file as the plan expected."),
            file=path, metric=metric, before=before, after=round(after, 2),
        ))
    return results


def check_standing_invariant(plan, repo, log_dir, command, inherited, registry_tests, timeout):
    """R-5.4: the suite green except the registry and what pre-flight recorded."""
    if not command:
        return record("standing-invariant", "not-run",
                      "no suite command is known, so the invariant could not be measured")
    result = suite.run(command, repo, timeout)
    failures, basis = suite.failing_tests(result.output)
    log = write_log(repo, log_dir, "standing-invariant.txt", f"$ {command}\n\n{result.output}")

    if result.timed_out:
        return record("standing-invariant", "not-run",
                      f"the suite timed out after {timeout}s", log=log)

    allowed = list(inherited) + list(registry_tests)
    unexpected = [name for name in failures if not _is_allowed(name, allowed)]

    if not result.ok and basis == "unrecognised":
        return record(
            "standing-invariant", "not-run",
            f"the suite exited {result.returncode} and no recognised reporter format was "
            "found in its output, so which tests failed could not be read. Whether this run "
            "caused new red is unknown and is reported as unknown.",
            log=log,
        )

    if unexpected:
        return record(
            "standing-invariant", "failed",
            f"{len(unexpected)} test(s) are red that were not red at pre-flight and are not "
            f"in the defect registry: {', '.join(unexpected[:12])}. This is breakage this run "
            "caused. R-6.4: repair it within the item's retry budget or revert it fully "
            "before failing the item — no item ends with the working tree dirtier than it "
            "found it.",
            log=log,
        )

    return record(
        "standing-invariant", "passed",
        (f"green except {len(inherited)} inherited failure(s) and {len(registry_tests)} "
         f"registry test(s)") if (inherited or registry_tests) else "the suite is green",
        log=log,
    )


# --------------------------------------------------------------------------------------
# Driving one item
# --------------------------------------------------------------------------------------


def registry_tests_for(plan):
    """Test names standing red in the defect registry, and the claims they belong to."""
    names, claims = [], set()
    for block in plan.by_kind.get("defect", []):
        test = block.node.get("test")
        if isinstance(test, dict) and isinstance(test.get("name"), str):
            names.append(test["name"])
        if isinstance(block.node.get("claim"), str):
            claims.add(block.node["claim"])
    return names, claims


def run_item(plan, item_id, repo, log_dir, preflight_record, mutated_files, timeout,
             coverage_command=None, coverage_report=None, skip=(), pending_defects=()):
    item = plan.node("work-item", item_id).node
    inherited = list((preflight_record or {}).get("baseline", {}).get("inherited_failures") or [])
    registry_names, registry_claims = registry_tests_for(plan)
    # A defect this very item is about to register is not in the registry yet — the block is
    # appended only once the item reaches `done-with-defect`, which is after these checks run.
    # Declaring it here is what stops the item that finds a defect from failing its own
    # standing invariant over the finding.
    registry_names = list(registry_names) + list(pending_defects)
    allowed = inherited + registry_names
    baseline = load_baseline(repo, log_dir)

    suite_command = (preflight_record or {}).get("baseline", {}).get("command")
    if coverage_command is None or coverage_report is None:
        derived_command, derived_report = coverage_source(plan)
        coverage_command = coverage_command or derived_command
        coverage_report = coverage_report or derived_report

    results = []
    for index, check in enumerate(item.get("completion-checks") or [], start=1):
        if not isinstance(check, dict):
            continue
        kind = check.get("kind")
        if kind in skip:
            continue

        if kind == "file-exists":
            results.append(check_file_exists(check, repo))
        elif kind == "tests-pass":
            results.append(check_tests_pass(check, repo, log_dir, timeout, allowed=allowed))
        elif kind == "guard-holds":
            results.append(check_guard_holds(check, repo, log_dir, timeout, allowed=allowed))
        elif kind == "pattern-count":
            results.append(check_pattern_count(check, repo))
        elif kind == "mutation":
            claim = check.get("claim")
            # R-7.4: a mutation against a claim whose test is standing red in the registry
            # proves nothing, so it is suspended rather than run. It activates when the test
            # goes green.
            if claim in registry_claims:
                results.append(record(
                    "mutation", "suspended",
                    f"{claim} has a test standing red in the defect registry, so mutating the "
                    "code against an already-failing test would prove nothing about the "
                    "suite's ability to detect the defect. The check activates when that test "
                    "goes green (R-7.4).",
                    claim=claim,
                ))
                continue
            results.append(check_mutation(
                check, repo, log_dir, timeout,
                (mutated_files or {}).get(str(index)) or (mutated_files or {}).get(claim),
            ))

    if item.get("claims"):
        results.append(claim_annotations.check(
            repo,
            [p for p in ((item.get("files-touched") or {}).get("test") or [])],
            list(item.get("claims") or []),
        ))

    if "coverage-delta" not in skip:
        results.extend(check_coverage_deltas(
            item, plan, repo, log_dir, coverage_command, coverage_report, baseline, timeout,
        ))

    if "standing-invariant" not in skip:
        results.append(check_standing_invariant(
            plan, repo, log_dir, suite_command, inherited, registry_names, timeout,
        ))

    return results


def verdict(results):
    """One word for the whole pass, and what it obliges the executor to do next."""
    if any(r["outcome"] == "failed" for r in results):
        return "failed"
    if any(r["outcome"] == "not-run" for r in results):
        return "incomplete"
    return "passed"


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--item")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--preflight", help="the pre-flight record; defaults to the sidecar copy")
    parser.add_argument("--mutation-check", help="run only this mutation, by check number or claim id")
    parser.add_argument("--mutated-file", help="the mutated content, prepared outside the repository")
    parser.add_argument("--coverage-command")
    parser.add_argument("--coverage-report")
    parser.add_argument("--skip", nargs="*", default=[],
                        help="check kinds to leave out of this pass")
    parser.add_argument("--pending-defect", nargs="*", default=[], metavar="TEST",
                        help="a test this item is about to register as a defect, which the "
                             "standing invariant and whole-suite checks must not count as "
                             "breakage. Only for a test you have already had verified as "
                             "faithful to a cited or ratified claim (R-7.3)")
    parser.add_argument("--timeout", type=int, default=suite.DEFAULT_TIMEOUT)
    parser.add_argument("--recover", action="store_true",
                        help="restore from an interrupted mutation and exit")
    parser.add_argument("--record-baseline", action="store_true",
                        help="measure and store the coverage baseline; run once, after slice zero")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    # Always, before anything else. A previous process may have been killed mid-mutation.
    recovered = recover(args.repo, args.log_dir)
    if recovered:
        print(f"recovered a mutation left in progress on {recovered['target']}: "
              f"{recovered['outcome']}", file=sys.stderr)
    if args.recover:
        if not recovered:
            print("nothing to recover: no mutation was left in progress")
        return 0

    plan = planio.Plan(args.plan, phase="executed", lint_writes=False)

    if args.record_baseline:
        command, report = coverage_source(plan)
        payload = record_baseline(
            args.repo, args.log_dir,
            args.coverage_command or command, args.coverage_report or report, args.timeout,
        )
        if payload.get("error"):
            print(f"no baseline recorded: {payload['error']}", file=sys.stderr)
            print(
                "  Every `coverage-delta` entry whose `baseline-source` is `slice-zero` will "
                "be reported not-run against this run, which is a narrowing to record rather "
                "than a number to invent.",
                file=sys.stderr,
            )
            return 1
        print(f"baseline recorded: {len(payload['files'])} file/metric figure(s) from "
              f"{payload['report']} ({payload['format']})")
        return 0

    if not args.item:
        parser.error("--item is required unless --recover or --record-baseline is given")

    preflight_path = args.preflight or os.path.join(args.repo, args.log_dir, "preflight.json")
    preflight_record = None
    if os.path.exists(preflight_path):
        with open(preflight_path, encoding="utf-8") as handle:
            preflight_record = json.load(handle)
    else:
        print(
            f"note: no pre-flight record at {preflight_path}. The standing invariant has no "
            "recording of inherited failures to measure against, so every pre-existing "
            "failure will look like breakage this run caused. Run preflight.py first.",
            file=sys.stderr,
        )

    mutated = {args.mutation_check: args.mutated_file} if args.mutation_check else {}

    if args.mutation_check:
        item = plan.node("work-item", args.item).node
        checks = [c for c in (item.get("completion-checks") or []) if isinstance(c, dict)]
        chosen = None
        for index, check in enumerate(checks, start=1):
            if check.get("kind") != "mutation":
                continue
            if str(index) == args.mutation_check or check.get("claim") == args.mutation_check:
                chosen = check
                break
        if chosen is None:
            print(f"no mutation check {args.mutation_check!r} on {args.item}", file=sys.stderr)
            return 2
        results = [check_mutation(chosen, args.repo, args.log_dir, args.timeout,
                                  args.mutated_file)]
    else:
        results = run_item(
            plan, args.item, args.repo, args.log_dir, preflight_record, mutated,
            args.timeout, args.coverage_command, args.coverage_report, tuple(args.skip),
            tuple(args.pending_defect),
        )

    overall = verdict(results)
    if args.json:
        print(json.dumps({"item": args.item, "verdict": overall, "checks": results},
                         indent=2, ensure_ascii=False))
    else:
        print(f"{args.item}: {overall}")
        for result in results:
            head = f"  {result['outcome']:9} {result['kind']}"
            if result.get("claim"):
                head += f" [{result['claim']}]"
            print(head)
            if result.get("detail"):
                print(f"      {result['detail']}")
    return 0 if overall == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run a test command and read its output. Shared by pre-flight and the check runner.

Two jobs, and the second is the one that earns this module its own file.

**Running a command as written.** The plan authors every command; R-2.3 forbids editing one,
which includes helpfully adding a reporting flag. So this runs exactly what the plan says and
reads whatever comes out, rather than choosing a format it would prefer.

**Telling an assertion failure from an error.** R-5.6 turns on this distinction: a mutation
check passes only when the named tests fail *by assertion*, because a test that errors under
mutation proves it reaches the code and proves nothing about what it asserts. Deleting a
function so every test importing it explodes would otherwise satisfy every mutation check in
the plan at once.

The classification is heuristic, and where it cannot decide it says `unknown` rather than
guessing. R-10.2 forbids inferring a check outcome, and a mutation check whose evidence could
not be read is reported as not-run — which is a worse outcome for the run and an honest one.
"""

import re
import subprocess

DEFAULT_TIMEOUT = 900


class RunResult:
    __slots__ = ("command", "returncode", "stdout", "stderr", "timed_out", "seconds")

    def __init__(self, command, returncode, stdout, stderr, timed_out, seconds):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.seconds = seconds

    @property
    def output(self):
        return self.stdout + ("\n" + self.stderr if self.stderr else "")

    @property
    def ok(self):
        return self.returncode == 0 and not self.timed_out


def run(command, cwd=".", timeout=DEFAULT_TIMEOUT):
    """Run one shell command from the repository root."""
    import time  # noqa: PLC0415

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return RunResult(
            command,
            completed.returncode,
            completed.stdout,
            completed.stderr,
            False,
            time.monotonic() - started,
        )
    except subprocess.TimeoutExpired as expired:
        return RunResult(
            command,
            None,
            expired.stdout.decode("utf-8", "replace") if expired.stdout else "",
            expired.stderr.decode("utf-8", "replace") if expired.stderr else "",
            True,
            time.monotonic() - started,
        )


# --------------------------------------------------------------------------------------
# Reading failures out of a run
# --------------------------------------------------------------------------------------

# pytest's short summary, which is the most reliable source it offers:
#     FAILED tests/test_money.py::test_scale - AssertionError: assert Decimal('1.2') == ...
#     ERROR tests/test_io.py::test_load
_PYTEST_SUMMARY = re.compile(
    r"^(?P<kind>FAILED|ERROR)\s+(?P<test>\S+?)(?:\s+-\s+(?P<reason>.*))?$", re.MULTILINE
)
# The inline form, printed as tests run with -v.
_PYTEST_INLINE = re.compile(r"^(?P<test>\S+::\S+)\s+(?P<kind>FAILED|ERROR)\b", re.MULTILINE)
# unittest.
_UNITTEST = re.compile(r"^(?P<kind>FAIL|ERROR):\s+(?P<test>\S+)", re.MULTILINE)
# vitest and jest mark a failing case with a cross, and jest's summary uses a bullet.
_JS_CROSS = re.compile(r"^\s*[×✕✗]\s+(?P<test>.+?)(?:\s+\d+ms)?\s*$", re.MULTILINE)
_JEST_BULLET = re.compile(r"^\s*●\s+(?P<test>.+?)\s*$", re.MULTILINE)

_ASSERTION_MARKERS = (
    "AssertionError",
    "assertionerror",
    "\nE       assert ",
    "\n    assert ",
    "expect(received)",
    "AssertionFailedError",
    "to be truthy",
    "toEqual",
    "toBe(",
    "assert_called",
    # A test that asserted an exception and did not get one. pytest calls this `Failed`
    # rather than `AssertionError`, and it is an assertion failure in substance: the test
    # stated what should happen and it did not. Without this marker, every mutation check
    # whose named test uses `pytest.raises` classifies as an error and fails — which is the
    # opposite of the truth, since deleting a `raise` is one of the cleanest behavioral
    # mutations there is.
    "DID NOT RAISE",
    "did not raise",
    "Expected exception",
    "to throw",
)

_ERROR_MARKERS = (
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "IndentationError",
    "NameError",
    "AttributeError",
    "TypeError",
    "ValueError",
    "ZeroDivisionError",
    "INTERNALERROR",
    "collection failure",
    "errors during collection",
    "Cannot find module",
    "ReferenceError",
    "is not a function",
)


def failing_tests(output):
    """Every failing test name the output names, and how confident that reading is.

    Returns ``(names, basis)``. ``basis`` is ``"parsed"`` when at least one recognised
    reporter format was found and ``"unrecognised"`` when none was — in which case the caller
    knows the command failed but not which tests, and must say so rather than assume none.
    """
    names = []
    seen = set()

    def add(name):
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for pattern in (_PYTEST_SUMMARY, _PYTEST_INLINE, _UNITTEST):
        for match in pattern.finditer(output):
            add(match.group("test"))
    for pattern in (_JS_CROSS, _JEST_BULLET):
        for match in pattern.finditer(output):
            candidate = match.group("test")
            if candidate.lower().startswith(("console", "stdout", "stderr")):
                continue
            add(candidate)

    return names, ("parsed" if names else "unrecognised")


# Every separator a runner puts between a suite name and a test name. pytest uses `::`,
# vitest and jest use a chevron, mocha uses a space. A plan names the test the way a person
# would say it — "parseSpec extracts the overview" — and the reporter prints
# "file.test.ts > parseSpec > extracts the overview". Those are the same test, and a matcher
# that cannot see that fails every mutation check written against a JavaScript runner.
_SEPARATORS = re.compile(r"\s*(?:::|>|›|❯|»|\|)\s*|\s+")


def _canonical(name):
    """One test name, reduced to the words in it. Separators and case do not survive."""
    return re.sub(r"\s+", " ", _SEPARATORS.sub(" ", name)).strip().lower()


def names_match(wanted, observed):
    """Whether a plan-named test appears among the failures a run reported.

    The plan names a test the way a person would — ``test_parse_amount_rejects_empty``, or
    ``parseSpec returns null for an empty document`` — and a reporter names it with its file
    and suite attached, in whatever separator that runner favours. Both sides are reduced to
    their words before comparing.

    Substring matching in both directions is deliberate rather than lax: an exact-match rule
    would fail every real check, and a check that can never pass is indistinguishable from one
    that was never written.
    """
    wanted = (wanted or "").strip()
    if not wanted:
        return False
    normalised = _canonical(wanted)
    if not normalised:
        return False
    for candidate in observed:
        flat = _canonical(candidate)
        if normalised in flat or flat in normalised:
            return True
    return False


def mentioned_in(output, name):
    """Whether a run's output names this test anywhere, in any separator style."""
    return _canonical(name) in _canonical(output)


def classify_failure(output, expected_count=1, observed_count=None):
    """Whether a failing run failed by assertion or by error. R-5.6's distinction.

    Returns ``(verdict, reason)`` where verdict is ``"assertion"``, ``"error"``, or
    ``"unknown"``. The reason names the signal that decided it, so a mutation check's
    recorded detail can say *why* rather than only what.

    Three signals, in order of how much they prove:

    1. **A collection or import failure anywhere.** The mutation broke the module rather than
       its behavior, so nothing it caused says anything about assertions. This outranks the
       others: a run can contain both a genuine assertion failure and a broken import, and
       the broken import is what a reviewer needs to hear about.
    2. **Far more failures than were named.** A mutation that makes one named test fail is
       evidence about that test. A mutation that makes forty tests fail has usually broken
       something structural, and the named test's failure is a side effect.
    3. **Assertion markers in the output** — an ``AssertionError``, a pytest ``assert``
       diff line, a jest or vitest ``expect(received)`` block.
    """
    if any(marker in output for marker in ("errors during collection", "INTERNALERROR",
                                           "ERROR collecting", "Cannot find module")):
        return "error", "the run reported a collection or import failure"

    has_assertion = any(marker in output for marker in _ASSERTION_MARKERS)
    has_error = any(marker in output for marker in _ERROR_MARKERS)

    if (
        observed_count is not None
        and expected_count
        and observed_count > max(expected_count * 4, expected_count + 10)
    ):
        return "error", (
            f"{observed_count} test(s) failed where {expected_count} were named, which is "
            "the shape of a structural break rather than of a falsified assertion"
        )

    if has_assertion and not has_error:
        return "assertion", "the output contains an assertion failure and no error type"
    if has_assertion and has_error:
        # Both present. Common and benign: a test asserting that a call raises TypeError
        # mentions the type in its own assertion message. The assertion signal is the more
        # specific of the two, so it wins, and the reason says the reading was mixed.
        return "assertion", (
            "the output contains an assertion failure alongside an error type name, which is "
            "usual when a test asserts about an exception"
        )
    if has_error:
        return "error", "the output contains an error type and no assertion failure"
    return "unknown", (
        "the output names neither an assertion failure nor an error type, so whether the "
        "test failed by assertion could not be read from it"
    )


def summarise(result, limit=4000):
    """A bounded excerpt of a run, for a `detail` field that has to stay readable."""
    text = result.output.strip()
    if result.timed_out:
        return f"timed out after {result.seconds:.0f}s running `{result.command}`"
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n[... {len(text) - limit} characters omitted ...]\n\n" + text[-half:]


def main():
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415
    import sys  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run(args.command, args.repo, args.timeout)
    names, basis = failing_tests(result.output)
    verdict, reason = classify_failure(result.output, 1, len(names))
    payload = {
        "command": args.command,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "seconds": round(result.seconds, 2),
        "failing_tests": names,
        "failure_basis": basis,
        "classification": verdict,
        "classification_reason": reason,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

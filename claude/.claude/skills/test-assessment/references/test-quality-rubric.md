# Test Quality Rubric

For every existing test, decide one thing first: **does this test verify behavior, or
does it merely execute code?** A test that only executes code produces coverage without
producing confidence, and that gap is the central finding of most assessments.

Classify weak tests into the categories below. Quote the specific lines that justify each
classification — a quality judgment without quoted evidence cannot survive the
verification pass.

A test may fall into more than one category. Record all that apply.

---

## Category 1 — No assertions, or only trivial ones

The test runs the code and checks nothing meaningful. It fails only if the code throws.

**What it looks like**

- No assertion statement at all
- Only `assert result is not None` or `expect(result).toBeDefined()`
- Only "it did not throw": a bare call, or `expect(() => f()).not.toThrow()`
- A React component test that renders and asserts nothing
- `assert True`, or an assertion comparing a value to itself

**Why it is weak.** It pins down almost nothing. Nearly any change to the function still
passes. It contributes coverage while contributing no verification.

**What it is not.** A test whose entire point is that a call does not raise — for example,
verifying that a parser accepts a known-good input — is legitimate *if* the report says
that is what it verifies. Judge intent, not just shape.

---

## Category 2 — Asserts against mocks rather than outcomes

The test verifies that a substituted function was called, instead of verifying what the
code produced.

**What it looks like**

- `mock.assert_called_once_with(...)` as the only assertion
- `expect(mockFn).toHaveBeenCalledWith(...)` as the only assertion
- Every collaborator mocked, so nothing real executes
- Assertions about call order and call count, but never about a returned value or a
  resulting state change

**Why it is weak.** It tests the code's implementation choices, not its behavior. It
passes when the code is wrong and fails when the code is correctly refactored — exactly
backwards. It also tends to encode the current call structure so firmly that the seam
refactorings recommended later become expensive.

**What it is not.** Mocking a genuine external boundary — a network call, a clock, a
payment provider — and then asserting on what the code *did with the result* is fine.
The failure mode is asserting on the mock instead of on the outcome.

---

## Category 3 — Restates the implementation

The test computes its expected value the same way the production code does, so a bug in
that logic changes both sides equally and the test still passes.

**What it looks like**

- The expected value is computed by reimplementing the formula inline
- The test imports the very constant or helper the code under test uses to build its
  result
- The assertion mirrors the code's structure statement for statement
- A test for a mapping that builds the expected mapping with the same loop

**Why it is weak.** It is a tautology. It cannot detect the class of bug it appears to
guard against. The tell is that reading the test tells you nothing about what the code is
*supposed* to do — only about how it currently does it.

**How to check it.** Ask: if the production logic were wrong in a plausible way, would
this test's expected value be wrong in the same way? If yes, Category 3.

---

## Category 4 — Unreviewed snapshot tests

The test froze whatever the code produced at the moment it was written, with no evidence
that anyone decided the output was correct.

**What it looks like**

- `toMatchSnapshot()` or `toMatchInlineSnapshot()` with a large committed snapshot
- `syrupy` or `pytest-snapshot` fixtures in Python
- Snapshot files far larger than any human reviewed
- Snapshots regenerated in the same commit as the change they should have caught

**Why it is weak.** It detects change, not incorrectness. When it fails, the habitual fix
is to regenerate it, which converts the test into a formality. It also cannot tell a
deliberate change from a regression.

**How to check it.** Look at the version control history for the snapshot file. If it was
updated in the same commit as production changes, repeatedly, without discussion, treat
it as unreviewed. If you cannot check the history, say the evidence was unavailable
rather than assuming either way.

**What it is not.** A small, readable, deliberately reviewed snapshot of a stable
serialization format is reasonable. Size and review evidence are what separate the two.

---

## Category 5 — Disabled, skipped, and expected-failure tests

Not a quality category so much as a silent subtraction from coverage. Find every one.

**Python**: `@pytest.mark.skip`, `@pytest.mark.skipif`, `@pytest.mark.xfail`,
`pytest.skip()` inside a body, and module-level `pytestmark = pytest.mark.skip`, which
disables an entire file.

**JavaScript and TypeScript**: `it.skip`, `test.skip`, `describe.skip`, `it.todo`,
`test.failing`, `xit`, `xdescribe`, and commented-out test blocks.

**`.only` deserves separate treatment.** A committed `it.only` or `describe.only`
silently disables every other test in that file while the suite still reports green. If
you find one, it is a top-tier finding regardless of anything else in the report.

For each, record the reason if it is stated, and "reason not stated" if it is not. Do not
invent a reason.

---

## The covered-but-unverified category

After classifying the tests, produce the list of production code that coverage counts as
covered but that no test meaningfully verifies. This is code reached only by tests in
Categories 1 through 4.

Report it as its own category, separate from uncovered code, because the two need
different work: uncovered code needs a test written, covered-but-unverified code needs an
existing test fixed or replaced, and the second is often the more urgent because it is
actively misleading.

This category is the reason the raw coverage number alone is insufficient, and it should
appear prominently in the executive summary when it is large.

---

## Recording a judgment

For each weak test, record: the file and line, the category or categories, the quoted
evidence, and what the test would need in order to verify behavior. Keep the last part to
a sentence — stage one recommends, it does not write tests.

When a test is genuinely good, say so. A report that only lists problems gives the reader
no way to calibrate the ones it lists.

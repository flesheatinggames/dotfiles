# Turning a Claim into a Test

The one judgment this stage retains, and the conventions around it.

## The rule everything else follows from

> **Write the test asserting exactly what the claim's text states. The claim is the
> specification; the code is not.**

You are not writing a test of what the code does. If you read the implementation and assert
what you find, the test can never disagree with the code — and a test that cannot disagree
with the code cannot surface a defect, which is half of what this stage is for.

So: read the claim. Write the test from the claim. Run it. If it fails, that is a finding, and
`references/defects-and-disputes.md` says which kind.

**When you cannot write the test without reading the implementation, the claim is too vague.**
That is a planning defect. Fail the item and say so rather than sharpening the claim yourself —
the claim is on the owner's ratification list and rewording it changes what they approved.

## The annotation convention

R-5.7 requires machine-readable claim annotations and leaves the form to this skill. It is a
comment:

```python
# claim: C12
def test_parse_amount_reads_the_german_separator():
    ...
```

```typescript
// claim: C12, C13
it("returns the same value for both renderings", () => { ... })
```

Also accepted: `/* claim: C12 */`, `<!-- claim: C12 -->`, several ids separated by commas or
spaces, and trailing prose — `# claim: C12 — the German separator case` reads well and parses.

The annotation attaches to the next test definition within six lines, or, where there is none,
to the enclosing test. Both placements are common and both are correct.

**A comment rather than a test-name convention, and the reason is the review gate.** A name
like `test_c12_case_3` is machine-readable and unreadable, and the plan's mutation checks name
tests by name — so the owner reads those names at the gate, and a gate full of identifiers is a
gate nobody reads carefully. The comment carries the identifier without spending the name, and
it survives renaming either the test or the file.

```bash
python3 <skill>/scripts/claim_annotations.py --repo . --plan docs/test-plan.md --item WI-06
```

## Writing the test

### Name it for what it asserts

`test_parse_amount_reads_the_german_separator`, not `test_parse_amount_2`. The plan's mutation
checks name tests, the defect registry names tests, and the owner reads both.

**The plan already named the test.** Every mutation check carries a `tests` list, and those
names are what the check runner looks for. Use them exactly. A test whose name differs from the
one the check names is a check that cannot pass, and R-2.3 forbids editing the check to match.

### Assert the claim, and only the claim

The commonest failure is asserting *more*, and it does not feel like a failure — it feels like
thoroughness. A claim about scale, tested by asserting a whole formatted row, has quietly
enshrined the row format too. Nobody ratified that, and when it breaks the defect registered is
against something the owner never agreed to.

One claim, one assertion of it. Several claims, several tests, each annotated.

### Derive the expected value from the claim

A claim says `parse_amount("1.234,56")` with a comma separator is `Decimal("1234.56")`. Write
`Decimal("1234.56")`. Do not run it first and write down what came out.

This is the discipline that makes the whole stage work, and it is the one the faithfulness
verifier is built to check — which is why that verifier is given the claim and the test and no
source code at all.

### Make the failure legible

The test may end up committed red and standing in the owner's pipeline. What it prints when it
fails is what they will read first. `assert totals["credits"] == Decimal("0.00")` prints both
values; a bare `assert is_correct(totals)` prints nothing anybody can act on.

### Set up through the seam the plan gave you

If the claim's target needed a seam, the seam item ran first and the plan says so. Use it —
pass the separator, pass the opener — rather than reaching around it by setting a process
locale or writing a temporary file. Reaching around the seam produces a test that passes today
and is an integration test, which is what the seam existed to avoid.

## Repairing tests rather than writing them

A `test-repair` item changes existing tests so they *can* fail. Its mutation checks are the
only evidence the work happened at all — coverage does not move, the files still exist, and the
tests still pass, whether the item was done well, done badly, or not done.

Two shapes:

- **Adding assertions.** The test already calls the right function with the right arguments and
  discards the result. Assert what the claim says about that result. Do not rewrite the
  arrangement unless the claim needs a case it does not set up.
- **Removing tests.** An item that deletes tests asserting nothing carries no claims, and
  verifies itself with a `pattern-count` expecting zero or a `file-exists` marked absent. Delete
  them; do not "improve" them into something the plan did not ask for.

## Characterization tests are different, deliberately

A characterization test pins what the code does **without asserting that it is correct**. That
is what makes it safe to write before anybody has agreed what correct means, and it is why
characterization items carry no claims.

So here, and only here, you *do* read the implementation and write down what it produces. Say
so in the test's own docstring, so that nobody later mistakes it for a specification:

```python
def test_parse_amount_current_behavior_for_a_grouped_number():
    """Characterization: records today's result, asserting nothing about whether it is right.

    Guards WI-05's seam. Delete once WI-06's real assertions land.
    """
    assert parse_amount("1,234.56") == Decimal("1234.56")
```

A characterization test that outlives its seam becomes a specification nobody wrote, which is
the failure mode this docstring exists to prevent.

## Before you call the item done

- Every claim in the item's `claims` list has at least one annotated test.
- Every test name the plan's mutation checks refer to exists, spelled exactly that way.
- No test asserts anything the claim does not state.
- No expected value was copied from a run.
- Nothing outside the declared footprint was touched.

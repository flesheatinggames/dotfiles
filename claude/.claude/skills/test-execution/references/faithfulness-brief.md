# The Faithfulness Brief

R-7.3's mandatory verification, run before any red test is allowed to stand.

**Unconditional, not sampled.** A deploy-blocking red raised over the executor's misreading is
the worst false alarm this stage can produce, and the state in which it happens is confidence —
which is exactly the state in which the executor would not catch it themselves.

## How to run it

One subagent, fresh context. It is given **the claim's text and the test, and nothing else**.

Not the code. Not the executor's reasoning. Not what the executor concluded. Not the observed
behavior. The verifier is answering one question — does this test assert this sentence? — and
every one of those would answer it for them.

The prompt below is verbatim. Fill the two placeholders and send nothing more.

---

```
You are verifying one thing, in isolation, and you have been given deliberately little.

Below are a claim and a test. Your only question is whether the test asserts what the claim
says. Not whether the claim is true. Not whether the code behaves that way. Not whether the
test is well written. Only whether a reader of the claim would recognise the test as an
assertion of it.

You have not been given the source code, and that is not an oversight. If the test's expected
value was derived from reading the implementation rather than from the claim, you should not
be able to tell — and the test should still make sense on the claim's own terms. If it does
not, that is the finding.

THE CLAIM
---------
{claim text, verbatim, and nothing else from the claim block}

THE TEST
--------
{the test function in full, with its helpers if it uses any}

Answer these four, briefly:

1. What does the claim assert? Restate it in your own words in one sentence.
2. What does the test assert? Restate that in one sentence, from the assertions alone.
3. Are they the same assertion? Say where they differ if they differ at all — including
   where the test asserts MORE than the claim, which is as much a mismatch as asserting less.
4. Does the test's expected value follow from the claim, or could it only have come from
   running the code? If you cannot tell, say so.

Then give exactly one verdict on its own final line:

VERDICT: faithful
VERDICT: unfaithful

Choose `unfaithful` if you are unsure. A test that stands red blocks a pipeline, and the cost
of a second look is minutes.
```

---

## Reading the verdict

**`faithful`** — the red test may stand. Record the verifier's note in the defect entry's
`verification` block and commit the test red.

**`unfaithful`** — the test was the problem, not the code. Fix it and retry against the item's
budget. **Do not register a defect**, and do not argue with the verifier by giving them the
code: what you would be doing is supplying the context whose absence was the point.

The linter enforces the outcome: a defect whose `verification.verdict` is anything but
`faithful` fails as `defect-unverified`, and one whose `brief` is not `faithfulness` fails as
`defect-wrong-brief`.

## Where the four questions come from

Each catches a different way a test drifts from its claim, and the third and fourth are the
ones that earn the pass.

- **Asserting more than the claim** is the common failure and it does not feel like one. A
  claim says amounts carry two places of scale; the test asserts the whole formatted row.
  The extra assertion is unratified, and when it fails the defect registered is against
  something nobody agreed to.
- **An expected value that could only have come from the code** is the failure that makes the
  whole exercise pointless. A test whose expected output was copied from a run is a test that
  cannot disagree with the code, so it can never surface a defect — and if it *is* red, the
  red is about something else entirely.

## When the claim itself is the problem

Sometimes the verifier will say, correctly, that the claim is too vague to be asserted at all.
That is not a faithfulness failure and it is not fixable by rewriting the test.

Fail the item and say so. A claim too vague to write a test from is a planning defect, and
reporting it is more useful than three more attempts at a test that cannot be right.

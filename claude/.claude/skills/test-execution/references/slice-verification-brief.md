# The Slice Verification Brief

R-8.3's judgment layer, run after a slice's items complete and before the slice is declared
done.

## What it is for, and how it differs from the other two layers

Three layers verify a new test, in increasing cost:

| Layer | Proves | Cannot prove |
|---|---|---|
| **Structural** — the claim-annotation check | Every claim has a test | That the test is any good |
| **Mutation** — a named edit makes a named test fail | The suite detects *that specific* defect | That it detects anything else, or that the assertion means what it appears to |
| **Judgment** — this brief | The assertions actually discriminate the claimed behavior | Nothing further; this is the last layer |

The gap this fills is real. A test can carry the right annotation, pass its mutation check, and
still assert almost nothing — because the mutation check verifies one edit, and a test that
asserts one incidental field of a returned object will catch an edit to that field while
missing everything else the claim covers.

## Coverage: full for top tier, sampled below

Mirroring stage one's verification pattern. Every `top`-tier item in the slice is verified in
full. Below that, sample: at least one item per slice and at least one test per claim category
the slice touches.

Whether a high rejection rate in the full tier should escalate the sampled tier to full within
the same run is deferred; this version uses fixed tiers. If you find yourself wanting the
escalation, record it as an observation for the requirements rather than doing it.

## How to run it

One subagent, fresh context, given **the slice's claims and the tests written for them**. Not
the executor's reasoning, not the diagnoses, not the check runner's output. The verifier is
judging the tests as a reader of the claims would.

The prompt is verbatim below.

---

```
You are judging a set of tests against the claims they were written for. Fresh eyes: you have
the claims and the tests, and nothing about how they came to be written.

For each claim below, one question: do the test's assertions actually discriminate the
behavior the claim describes — or would they also pass against code that does not have that
behavior?

The failure you are looking for is a test that looks thorough and checks little. Some shapes
it takes:

  * it asserts something incidental to the claim — a length, a type, a key's presence — while
    the claim is about a value;
  * it asserts only the happy path of a claim that describes a boundary or an exception;
  * it asserts an object's identity or truthiness rather than its content;
  * it calls the function and asserts nothing at all about what came back;
  * its expected value is computed by the same expression the code under test uses, so the two
    cannot disagree;
  * it is parameterised over cases that are all the same case.

CLAIMS AND TESTS
----------------
{for each claim: its id, its text verbatim, then the full source of every test annotated with
that claim id}

For each claim, answer:

1. Which of the test's assertions bear on the claim, and which are incidental?
2. Name one plausible wrong implementation that satisfies the claim's words in appearance and
   would still pass these tests. If you cannot name one, say so plainly — that is the good
   answer.
3. Verdict for this claim: `discriminating` or `weak`.

Then, for the slice as a whole:

4. Is any claim asserted only indirectly, through another function's behavior, where a direct
   assertion was available?

End with one line per claim:

C12: discriminating
C13: weak — <the wrong implementation that would pass>
```

---

## Reading the result

**`discriminating`** — record it in the item's execution log `verifier` list and move on.

**`weak`** — the item reopens against its **retry budget**. Strengthen the assertions and run
the item's checks again. This is not advisory: R-8.3 says a slice with weak assertions fails as
a slice rather than surviving to the final report, so a `weak` verdict you did not act on is a
slice you may not declare done.

If the budget is exhausted and the verdict is still `weak`, the item is `failed` with the
verifier's named wrong implementation in the diagnosis. That is a much more useful failure than
a passing item nobody trusts.

## Why the second question is the one that works

"Name one plausible wrong implementation that would still pass" is the whole brief. Asking
whether a test is good invites agreement; asking for a counterexample invites work, and either
produces something specific or produces a specific admission that it could not.

It is also the same move the mutation check makes, done by a reader rather than a script — which
is why the two catch different things. The mutation check runs one edit somebody thought of at
planning time. This asks a fresh reader to think of a new one, with the claim in front of them
and no attachment to the test.

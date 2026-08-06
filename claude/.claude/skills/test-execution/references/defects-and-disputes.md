# Defects and Disputes

What to do when a test you wrote faithfully fails. R-7.1 to R-7.6.

**This is the subtlest thing in stage three and getting it backwards is the worst mistake
available here.** Two failures that look identical — you wrote the test the claim describes,
the test went red — have opposite handling, and which one you are looking at is decided by one
field on the claim.

## The rule

> **For every claim, write the test asserting exactly what the claim's text states. The claim
> is the specification; the code is not.**

That is R-7.1, and everything below follows from it. You are not writing a test of what the
code does. You are writing a test of what the claim says, and a disagreement between them is
the finding.

## The fork

| The claim's label | Its backing | A faithful test that fails means | So you |
|---|---|---|---|
| `cited` | A requirements document, quoted inline | **The code is wrong** | Commit the test red. Register a defect. Mark the item `done-with-defect` |
| `ratified` | The owner said so personally at review | **The code is wrong** | The same |
| `pinned` | The planner's reading of the code, which nobody ratified | **The planner's reading was wrong** | Commit nothing. Capture evidence. Mark the claim `disputed`. Fail the item |

The asymmetry is about authority, not about severity. A cited claim carries a document's
authority and a ratified one carries the owner's; neither can be overruled by an agent
mid-run, so the code is what is at fault and a red test is how that gets said. A pinned claim
has no such backing — it is one reading of some lines — so a failing test impeaches the
reading.

**Committing a red test for a pinned claim would block the pipeline over a fiction:** a test
asserting behavior that never existed and that nobody ever agreed should exist.

## Defects — the cited and ratified case

### 1. Spend the retry budget on one question only

*Is my test faithful to the claim?* Not "is the code right" — that is not yours to decide.
Unfaithfulness is fixed and retried. Faithful means: it asserts what the claim's sentence
states, no more and no less, and its expected value follows from the claim rather than from
reading the implementation.

### 2. Get it verified, always

Before the red test stands it receives **mandatory** fresh-context verification — not sampled,
not skipped when you are confident. Use `references/faithfulness-brief.md`, which gives the
verifier the claim's text and the test and **nothing else**: not your reasoning, not the code,
not what you concluded.

A deploy-blocking red raised over your own misreading is the worst false alarm this stage can
produce, and confidence is exactly the state in which you would not catch it. That is why the
check is unconditional.

If the verdict is anything but `faithful`, the test was the problem. Fix it and retry.

### 3. Commit it red

**No known-failure marker. No skip. No softening. No comment explaining it away.** The red test
*is* the enforcement mechanism: it blocks the owner's pipeline until someone makes a recorded
decision about the defect, which is the point rather than a regrettable side effect.

### 4. Register it, and mark the item `done-with-defect`

```yaml defect
id: DF-1
claim: C1
item: WI-06
observed: >
  What the code actually does, stated so the owner can decide without running anything.
test:
  file: tests/test_money_parse.py
  name: test_parse_amount_reads_the_german_separator
verification:
  brief: faithfulness
  verdict: faithful
  date: "2026-08-01"
  note: >
    Fresh context, given only C1's text and the test.
commit: 1d9f8e2
suspended-mutations:
  - C1
resolution: null
```

**`done-with-defect` is not a failure.** You wrote the test the claim describes, the test
failed, and the test is faithful — so the item was done correctly and the code is what is
wrong. Marking it `failed` would blame the work for finding the thing it was written to find,
and stage four would then be unable to tell a plan that did not work from a plan that worked
and surfaced a bug.

**Leave `resolution` null.** It is the owner's answer at close-out.

### 5. Suspend the mutation checks

Any mutation check against a registry claim is recorded `suspended`, never passed (R-7.4).
Mutating code against an already-failing test proves nothing. List the claims in
`suspended-mutations` so the report can say what is outstanding.

### What the owner may do at close-out, and what you may not

R-7.6 gives four options, and they are theirs:

- The code is wrong and will be fixed — the red test is the ready-made verification, tracked
  and re-reported by any later run until it goes green.
- The requirement is wrong — the test is rewritten to assert observed behavior as a normal
  green test, the claim is relabelled `ratified-as-observed`, and the report flags the
  requirements document itself for amendment.
- The branch is accepted with the red tests standing, letting continuous integration enforce.
- The defect is explicitly downgraded to a known-failure marker, recorded as their decision.

**The fourth is never available to you** (R-2.5). Neither, in practice, is the second: relabelling
a claim you wrote the test for is marking your own homework.

## Disputes — the pinned case

### 1. The same first step

Spend the retry budget on faithfulness. Most pinned-claim failures are unfaithful tests, and
the ones that are not are worth reporting precisely.

### 2. Capture the evidence

The test as written and the observed behavior, in the sidecar log or on a side branch. The
dispute's entire weight rests on this, because unlike a defect it leaves nothing behind in the
suite. A dispute with no evidence is an unbacked assertion that the planner misread the code,
made by the party who would otherwise have to write the test.

### 3. Mark the claim, then nothing else

```bash
# evidence first, then the label -- the linter requires the pointer to exist
python3 <skill>/scripts/planio.py docs/test-plan.md --set-claim C9 evidence docs/test-execution-log/C9-dispute.md
python3 <skill>/scripts/planio.py docs/test-plan.md --set-claim C9 label disputed
```

### 4. Fail the item, and commit nothing

The claim was the specification the item was written against and it did not hold, so the item
did not deliver what it promised — however correct your work was. The diagnosis says what the
code actually does and why the reading was wrong, which is what makes the re-plan cheap.

**Nothing red is committed, and nothing green either.** Other tests in the same item may have
passed; they go with it. The item is the unit, and committing half of it would leave the plan
saying an item completed when its own claims list says otherwise. The work is preserved on the
side branch named in the execution log.

## The one thing to check before you decide which of these you are in

**Read the claim's `label` field.** Not its `source.kind`, not how confident the wording
sounds, not whether the plan quotes a document somewhere nearby. The label is the field the
owner ratified against and the field the linter checks, and it is the whole of the question.

A cited claim whose test fails and gets marked `disputed` silently downgrades a deploy-blocking
finding to a note. A pinned claim whose test fails and gets committed red blocks a pipeline
over one person's reading of some lines. The linter catches both — `defect-claim-not-cited`
and `disputed-without-code` — but by then the work has been done twice.

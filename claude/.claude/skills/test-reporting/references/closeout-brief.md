# The close-out gate, written to the owner

This is written to you, the repository's owner, rather than to the model. It explains what you
are being asked to decide, why nobody else may decide it, and what each answer costs. The model
reads it too, so that it can answer your questions about the options without inventing
anything — but it is not permitted to answer them for you.

## What a defect is here

The pipeline wrote a test for a specific stated behavior, and the test failed. Before that
failing test was allowed to stand, a separate agent with no knowledge of the executor's
reasoning was given the claim's text and the test and nothing else, and confirmed that the test
asserts the claim and nothing further. That check is unconditional and it exists because a
deploy-blocking red raised over a misreading is the worst false alarm this pipeline can
produce.

So a defect is not "a test is failing". It is: *a behavior that a requirements document
specified, or that you personally confirmed was intended, is not what the code does.*

The failing test is committed and it is red on the branch right now. That is the enforcement
mechanism rather than an oversight — it blocks the pipeline until you make a recorded decision,
which is the point.

## Why the decision is yours

A claim gets its force from where it came from. A `cited` claim carries a requirements
document's authority; a `ratified` claim carries yours, because you confirmed it at the review
sitting. The authority to declare either one non-blocking belongs to whoever made it binding.

That is why no part of this pipeline may answer for you, and why one of the four options below
is not available to an agent at any point, under any circumstances.

## The four answers

### `fix-the-code`

The code is wrong and someone will fix it.

Nothing changes on this branch now. The red test stays red and becomes the ready-made
verification for whoever does the fix — they know they are done when it goes green. The defect
stays open in the run ledger, and every later run re-reports it until it does.

**Cost.** The suite is red until the fix lands, so anything that gates on a green suite is
blocked. If nothing is scheduled to do the fix, this answer and `accept-with-red` differ only
in what you intend, and the ledger will tell the same story about both in six months.

### `requirement-wrong`

The claim was wrong and what the code does is acceptable.

The failing test is rewritten to assert the observed behavior, the claim is relabelled
`ratified-as-observed`, and the document that specified something else is flagged for amendment
and tracked in the ledger until somebody amends it or contests the flag.

**Cost.** A behavior that a document called specified becomes a behavior the code merely has.
In the report's accounting it moves from the specified column to the pinned column, which is a
real reduction in what the suite is asserting — the test now says "this is what it does" rather
than "this is what it must do". And a document is now known to be wrong; the flag is what stops
that being forgotten, but the flag is not the amendment.

**This is the one answer that needs the model's help.** Writing the replacement assertion is a
judgment: a generated one would assert whatever the code currently returns, which is a
characterization pin wearing a specification's label. You will be shown the rewrite before it
is committed.

### `accept-with-red`

The defect is real, the branch merges anyway, and continuous integration carries the
enforcement rather than this suite.

Nothing changes on this branch.

**Cost.** The same as `fix-the-code`, with no expectation of a fix. A standing red that nobody
is working toward becomes background noise within about two weeks, and after that the suite has
one failure everybody has learned to ignore — which is the state in which the next real failure
also gets ignored. Choose this only when something outside the repository is genuinely watching
the red.

### `downgrade`

A known-failure marker is applied, so the suite reports green over a defect that is still real.

**This answer is available to nobody but you.** No agent may reach it, not at any point in this
pipeline. Its record is the strictest of the four for that reason: it names you, it names where
the marker went, and the marker itself must name the defect so that anyone who finds it in the
code can reach this decision, its rationale, and your name.

The marker is written with `strict=True` where the runner supports it, which means that if the
defect is ever fixed the marker itself starts failing. That is deliberate: it is the only way a
downgraded defect announces its own resolution rather than sitting marked forever.

**Cost.** The failure stops being visible. That is the point of the answer and it is also the
entire risk, and there is no version of this option where those are separable.

## How to record your answer

Run `closeout.py --brief`, which writes `docs/test-closeout.md`. Under each defect there is an
`answer` block. Fill it in:

```yaml answer
defect: DF-1
option: requirement-wrong
decided-by: "R. Okonkwo"
date: "2026-08-04"
rationale: >
  The specification's locale sentence was written for a product that never shipped a
  non-English locale. Making the parser locale-aware is real work with no current caller, and
  the two-decimal behavior the code has is what every consumer already depends on.
amendment-document: docs/spec.md
amendment-passage: "Amounts are parsed using the active locale's decimal separator and grouping character."
```

Four fields are always required and the linter enforces each for a reason:

- **`option`** — one of the four above.
- **`decided-by`** — your name. A decision with no decider is one an agent could have made.
- **`date`** — quoted, so no YAML parser turns it into a timestamp object.
- **`rationale`** — at least a sentence or two. A later run re-reports an open defect, and the
  person reading it then needs to know what was already weighed. "Not now" is not that.

`requirement-wrong` also needs the document and the passage. `downgrade` needs a marker form
only when the runner is not pytest.

## Disputes

Below the defects you will find any *disputes*. These are different and they do not block.

A dispute is a claim the planner read out of the code — nobody specified it, nobody ratified it
— which a faithful test then contradicted. The claim's only backing was the planner's reading,
so the failure impeaches the reading rather than the code. Nothing is red on the branch and
nothing blocks the merge.

You can answer one, and you do not have to. `correct-the-claim` records what the claim should
have said, which the next round of planning starts from instead of rediscovering the same
misreading. `leave-disputed` records that you read it and left it. Both are answers; an
unanswered dispute stays an open ledger item and feeds the report's planner-accuracy finding,
which is how the pipeline finds out how often its own readings are wrong.

## One sitting

The gate is one sitting and a partially answered sheet is refused rather than half-applied.
Half a gate is decision debt that looks like progress: the plan would record some decisions,
the branch would carry some consequences, and nothing would say which defects had been thought
about and which had merely not been reached yet.

If the set is genuinely too large for one sitting, that is worth saying out loud — it means the
run surfaced more contradictions between the documents and the code than anybody expected, and
that is itself the most interesting finding of the run.

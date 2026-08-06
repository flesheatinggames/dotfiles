# The Review Sitting

What the owner does at the human gate, and how their decisions are written back into the plan.

Give this file to the owner along with the plan. It is written to them, not to the model.

---

## What this is

The plan is a proposal. Nothing in it happens until you approve it, and four kinds of decision
are yours to make. R-12.3 says they happen in one pass, because a review split across several
sittings tends to become a review that does not happen.

**You should not need to open the repository.** Every claim carries its source, every cited
claim carries the document's own words, and every escalation quotes both sides. If you find
yourself opening files to answer a question the plan asks, that is a defect in the plan —
tell whoever produced it, because the next one can be fixed.

Budget roughly an hour for a plan of forty to fifty claims. Two hundred claims — the maximum
the sizing rules allow — is a long sitting rather than an impossible one, and a plan that
would take longer than that has set its scope too wide and should be narrowed before you
start.

---

## The four decisions

### 1. Resolve the escalations

Section 1 lists every place the code and a document disagree. Both sides are quoted.

You are deciding **which side is right**, and the reason it cannot wait is that whichever side
a test asserts gets enshrined. Once a passing test says the code is correct, the specification
has been amended by implication and nobody recorded it.

Write your answer into the block's `resolution` field, naming the option:

```yaml
resolution: "E1-a. The specification is the contract; the rounding is a bug. Change the code."
```

You may also leave one open. An unresolved escalation degrades scope rather than blocking the
run: stage three skips the items that depend on it and the stage four report says which and
why. That is a legitimate choice, and saying so explicitly is better than deciding under time
pressure.

### 2. Ratify the pinned claims

Section 4 is the claim ledger. Every claim is labelled one of two ways:

- **`cited`** — a requirements or specification document says so, and the document's words are
  quoted beside it. Nothing to decide; you are only checking the quote says what the claim
  says it says.
- **`pinned`** — read from the code. It describes what the code currently does, which **nobody
  has ever agreed is correct**. The code's line is quoted beside it.

Ratifying a pinned claim means: *yes, that is what this should do, and a test asserting it is
asserting something real.*

This is the point of the whole distinction. Without it, a test suite grows by writing down
whatever the code happened to do on the day it was written, and the suite then defends that
behavior against every future change — including changes that were fixing it. A pinned claim
you ratify becomes a requirement. A pinned claim you do not is a bug you have just found.

For each one, mark it:

```yaml
label: ratified
ratified-by: "<your name>"
ratified-on: "2026-08-04"
```

Leave the ones you do not agree with as `pinned` and say why in `notes`. A claim you reject is
worth more than one you wave through — it is a defect found before a test enshrined it.

**Inconsistent pinned pairs** get special attention. These are two pieces of code that do the
same thing differently, with no document covering either. Ratifying one and rejecting the
other is the useful answer: it turns "these disagree" into "this one is wrong."

### 3. Answer the decisions

Section 1 also lists choices about scope or approach that the plan was not authorized to make
— whether to commit a fixture directory, whether to lower a threshold, whether to implement
placeholder tests or delete them. Each states the options and what each costs.

Some carry a recommendation. A recommendation is a view, not a default; the plan is required
to make the recommendation visible rather than acting on it.

Some carry an experiment that would settle the question with a fact. Where one is offered, it
is usually worth running before the sitting rather than deciding in it.

Write into `resolution` the same way.

### 4. Approve or adjust the target

Section 3 proposes a coverage target and argues for it. You can approve it, change the number,
change the axes, or narrow the scope.

Two things to check:

**Is the baseline real?** The target says whether each figure is `measured` or `estimated`. A
target built on an estimate is worth approving only if you understand what would make it
exact, and the plan should say — usually installing the repository's dependencies and
re-running the assessment.

**Does the target have a re-derivation trigger?** When slice zero changes the coverage
denominator — by setting a collection scope or an omit list — the number cannot be approved
yet, because the thing it is a percentage *of* does not exist. In that case you are approving
the *shape* now and the *number* after slice zero runs. The plan says so explicitly; if it
does not and slice zero touches coverage configuration, ask.

```yaml
approved: "Approved as stated. Re-derive axis 1 after slice zero and send me the number."
```

---

## Things worth pushing back on

- **A claim you cannot check from the plan.** A cited claim with no quote, or a quote that does
  not say what the claim says. This is the one thing the automated checks cannot catch, which
  is why it is worth your attention.
- **A mutation whose edit would not actually falsify its claim.** Every asserted claim now
  carries either a mutation check or a waiver, and the linter guarantees the pairing exists.
  What it cannot check is whether the named edit really breaks the named claim — that is a
  reading of two sentences, and it is yours. An item whose checks are all satisfiable without
  the code getting better is an item that passes whether it was done well, badly, or not at
  all.
- **A `mutation-waiver` whose reason is that the work is inconvenient.** The bar is that no
  small named edit exists that would falsify the claim. "Hard to mutate", "the test is
  indirect", and "covered by the other checks" are all statements that it is awkward, not
  that it is impossible. Held to the same standard as the guard waiver.
- **A slice you would not want to stop in the middle of.** Slices are meant to be finishable in
  a session with a clean commit boundary.
- **A target you could meet without the suite getting better.** If the plan's central finding
  is that tests cannot fail, a target on coverage alone does not measure the fix.
- **Anything you had to open the repository to understand.**

---

## After the sitting

Save the file with your resolutions in it. The plan is the running record: stage three writes
execution status back into this same file, and stage four builds its report from it. Your
decisions are part of that record permanently.

Then re-run the linter, **with `--phase reviewed`**:

```bash
python3 <skill>/scripts/plan_lint.py docs/test-plan.md \
        --assessment docs/test-assessment.md --phase reviewed
```

The flag matters. By default the linter rejects a plan that arrives with resolutions already
filled in, because a planner writing one would be deciding something it was not authorized to
decide. `--phase reviewed` says those decisions are yours and expects them.

It rejects a `ratified` claim with nobody named. That is deliberate: an approval with no
approver is not an approval.

### Check the option's `effect` before you resolve

Where answering a question changes what a blocked item actually is — different checks,
different effort, or no item at all — the option says so in an `effect` block listing the
rewrite per item. Read it: it is the clearest statement of what your answer costs, and it is
more concrete than the prose consequence above it.

The item itself is written out as one of the answers, and its justification says which. The
effects on the other options are the diffs from that. Applying them is a manual edit, which is
deliberate — nothing rewrites the plan on your behalf.

### Resolving a blocker takes three edits, not one

The linter will walk you through them, but it is easier if you know in advance. When you
resolve an escalation or a decision, first apply the chosen option's `effect` if it has one,
then:

1. **Move each item it blocked from `blocked-on-decision` to `pending`,** and remove the
   blocker from that item's `blocked-by`. Leaving it blocked means stage three skips work you
   just unblocked — the linter reports this as `resolved-but-still-blocked`.
2. **Remove the item from the blocker's own `blocks` list.** The link is checked in both
   directions, because a one-sided link means one of the two entries is wrong and there is no
   way to tell which.
3. **If a slice carried a `demoted-fully-blocked` deviation and is no longer fully blocked,
   remove the deviation and move the slice back to its risk position.** The plan's
   justification for the demotion says where it belongs.

None of this needs a fresh planning run. It is mechanical, and the linter names every edit
that is still outstanding.

Items whose blocker you left open stay `blocked-on-decision`, stage three skips them, and the
stage four report says which and why.

# Conflict Catalog — Three Decision Classes

Everything the plan cannot decide for itself becomes an entry in the decisions-required
section. There are exactly three kinds, and each has a recognition test that does not depend
on how the conflict feels.

Getting the class right matters because the classes behave differently. A `flagged` entry
never blocks anything. An `escalation` blocks the items that depend on the answer. A
`decision` blocks whatever its options would change. Misclassifying one either blocks work
that could proceed or lets work proceed that should have waited.

---

## The recognition test

Ask two questions in order.

**1. Does implementing code exist?**

No → **`flagged`**. Stop here. It does not matter how important the behavior is.

**2. Is there a document that says what should happen?**

Yes, and the code does something else → **`escalation`**.
No, or the document is silent on the point at issue → **`decision`**.

That is the whole test. What follows is what each class means and how to write it.

---

## Class 1 — `flagged`: documented behavior with no implementing code

A document specifies something and nothing implements it.

**Why it is never a work item.** Writing production code is outside this skill's charter.
Stage three writes tests; it does not build features. An item asking it to test behavior that
does not exist is an item it cannot do.

**Why it is never a blocker either.** Nothing in this plan can wait on it, because nothing in
this plan will cause it to be implemented. An item marked `blocked-by` a flagged entry would
wait forever. The linter rejects this.

**Why it is recorded at all.** This finding class is invisible to coverage tooling — coverage
cannot report on code that does not exist — so if the plan does not say it, nothing will. It
is also easy to mistake for an untested behavior, which is a different and much less serious
thing.

**How to write it.** Give the document location and its words. Then state **how you
established the code is absent**: the searches you ran, not just the conclusion. "No
occurrence of `strict` under `ledger/` outside comments, and the argument parser at
`ledger/__main__.py` defines four flags, none of them `--strict`" is evidence. "Not
implemented" is an assertion.

**Real example.** A specification requires a `--strict` flag that rejects unbalanced entries.
No code mentions `strict`. Flagged, with the search recorded, and a backlog entry noting that
if the owner implements it, it becomes a finding for the next assessment rather than an item
in this plan.

---

## Class 2 — `escalation`: the code contradicts a document

A document specifies behavior and the code does something else.

**Why it is never decided silently.** Whichever side a test asserts gets enshrined. Write a
test asserting the document and you have declared the code a bug; write one asserting the
code and you have amended the specification by implication. Both are the owner's call, and
both are far cheaper to make now, while nothing pins either side, than after a green test
does.

**How to write it.** Both sides, each with a location and a quote. Then the plausible
resolutions with what each one costs. A `recommendation` field is permitted and often
helpful — absolute rule 4 forbids *silently choosing*, not offering a view — but the
recommendation must be visibly a recommendation, and the items stay blocked either way.

`blocks` names the items that depend on the answer, and each of those items names the
escalation in `blocked-by`. The linter checks both directions, because a one-sided link means
one of the two documents is wrong and there is no way to tell which.

**Real example.** `docs/spec.md` §4.2 requires banker's rounding. `ledger/money.py:41` uses
`ROUND_HALF_UP`. Both quoted; two resolutions, one changing the code and one changing the
document; the consequence of each stated; the unit-test item for `round_balance` blocked.

Note what the plan can still do while that is open: it can claim the *scale* half of the
specification passage, which both sides agree on, and it can claim that the rounding is
symmetric across signs without naming a mode. Splitting a claim to isolate the contested part
is often better than blocking the whole area.

---

## Class 3 — `decision`: a scope or approach choice the planner may not make

A choice that changes what gets built, where no document settles it and no code contradicts
anything.

**Why this class exists.** The first two classes do not cover everything, and the gap is not
hypothetical. In one real repository the most consequential planning question was whether to
commit a fixture `product/` directory so the loaders could be characterized against real
data. The build tool's globs are root-relative, so such a directory changes what the
development server shows and what the build ships. There is no document about it and no code
contradiction. Without a third class the planner has to mislabel it as an escalation or
decide it silently, and deciding it silently is exactly what rule 4 forbids.

**What belongs here:**

- Committing test fixtures that change what the application does at runtime
- Whether to lower or scope a coverage threshold when a measurement change would fail the build
- Whether to implement placeholder tests or delete the file holding them
- A contested assessment finding you could not resolve by reading the evidence (R-4.3 routes
  it here)
- Whether to grant a lint exemption or move code to satisfy a rule
- Any question where two answers produce materially different plans

**What does not:** anything you can settle by reading the code. A decision block for a
question with a fact behind it wastes the owner's attention on something an experiment would
answer. When there is an experiment, say what it is — one real decision block reads "Run the
experiment before the review sitting if there is time. This is a question with a fact behind
it, and a fact is cheaper to establish than to decide."

**How to write it.** The question, enough context that the owner does not have to reconstruct
it, at least two options with consequences, and `blocks`. A `recommendation` is permitted.

---

## Code contradicting code

Two pieces of code duplicate the same logic and behave differently, with no document covering
either. R-5.4 as originally written does not cover this: it is not a missing implementation
and there is no document to contradict.

**It is not an escalation**, because there is no specification side. **It is not a decision**
either, at least not yet — the planner does not need an answer to proceed. It needs the owner
to notice.

The handling is two pinned claims plus a grouping:

1. A pinned claim for each side, each describing what that code **actually does**. Do not
   write one claim describing what you think both should do — that is choosing a side while
   labelling it an observation.
2. An `inconsistent-pinned-pair` grouping on the ratification list, presenting the two
   together with a note that they duplicate the same logic and differ.

The owner then ratifies both, neither, or one — and ratifying one is the moment the
inconsistency becomes a bug report rather than a curiosity. `merge_claims.py` resolves the
grouping from the symbol names the reader supplied and fails when fewer than two of them
matched a claim, because a pair with one member is not a pair.

**Real example.** One repository has `slugify`, which strips a trailing hyphen, and
`getStorageKey`, which does not, built from the same substitution. Their outputs are never
compared, so nothing is visibly broken; the assessment ranked it Medium for exactly that
reason. Two pinned claims, grouped, with a note that neither is documented.

---

## What each answer does to the items it blocks

R-6.4 says what happens when an escalation or a decision goes **unresolved**: the blocked
items are skipped and the stage four report says so. Nothing said what happens when one is
**resolved**, and that gap has a specific cost.

An item blocked on a decision often means different work under different answers. Written
naively, the difference goes into the item's prose — "the mutation check applies only under
option a and should be dropped if the file is deleted". That is one item wearing one
identifier while being two different pieces of work, and it quietly breaks the rule that
matters most: R-7.1 requires every completion check to be **machine-checkable as written**,
and a check carrying a sentence saying it applies only under one answer is not. The executor
has to interpret, which is the one thing the plan exists to prevent.

So each option may carry an `effect`: the rewrite that answer implies, per item.

```yaml
options:
  - id: DEC-02-b
    summary: "Delete the file."
    consequence: "The suite drops to 1,149 tests and those components report as uncovered."
    effect:
      - item: WI-13
        set:
          title: "Delete the placeholder test file and record its requirements in the backlog"
          effort:
            unit: hours
            value: 1
        remove-checks:
          - mutation
        remove-claims:
          - C32
          - C33
        note: >
          The mutation check goes because there would be no test left to fail. The
          pattern-count check is unchanged and still holds: a deleted file contains zero
          placeholder bodies.
```

| Field | Means |
|---|---|
| `item` | Which blocked item this rewrites. It must be one the blocker actually blocks |
| `drop` | The item does not exist at all under this answer. Cannot be combined with the others |
| `set` | Field replacements, keyed by work item field name and validated against the work item schema, so a misspelling is a lint failure rather than a silent no-op |
| `unset` | Fields removed entirely — what a seam losing its `guarded-by` needs. A required field cannot be unset |
| `remove-checks` | Completion checks that do not apply, by kind. The kind must actually be present |
| `remove-claims` / `add-claims` | Claims the item stops or starts asserting |
| `note` | Anything the rewrite cannot express, including why a check that looks answer-dependent is in fact unchanged |

**An option with no `effect` means the blocked items execute exactly as written.** That is
the common case and it needs no ceremony.

**Write the item out as one answer and let the others rewrite it.** Pick the largest or most
likely answer as the written form, so the effort and the checks describe real work rather
than a lowest common denominator, and say in the justification which answer the written form
is. The owner then sees a concrete item and a concrete diff per alternative, rather than an
item they have to reconstruct.

**The linter catches the prose version of this.** If a blocked item's title, justification, or
notes mentions one of its blockers' option identifiers, that option must carry an `effect` for
it. Either state the difference mechanically or reword so the prose does not describe an
answer-specific outcome. The rule was written after this defect appeared eleven times across
three plans that were otherwise clean, so it is not a hypothetical.

**Effects are applied by the owner at review, not by any script.** The plan is re-linted
afterwards with `--phase reviewed`, at which point the item stands or falls on its own.

## Where each class ends up in the plan

| Class | Block | Blocks items? | Section |
|---|---|---|---|
| `flagged` | `yaml flagged` | Never — the linter rejects it | Decisions required |
| `escalation` | `yaml escalation` | Yes, and the link is checked both ways | Decisions required |
| `decision` | `yaml decision` | Yes, same check | Decisions required |
| Code-versus-code | Two `yaml claim` blocks plus a grouping | No | Ratification list |

All three of the first kinds appear in the decisions-required section at the top of the plan,
because that is where the owner starts and the whole section is what the review sitting works
through. An unresolved entry degrades scope; it never blocks the run (R-6.4).

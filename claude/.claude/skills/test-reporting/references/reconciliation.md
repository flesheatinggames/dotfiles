# Reconciliation: the backward obligations onto stages one and two (R-7.2, R-7.3)

Stated once, here, and referenced from both of those skills rather than restated in either.

## What makes the ledger binding

The run ledger is not a log. R-7.2 makes it binding: **a new assessment on a repository with a
ledger must explicitly confirm, update, or contest every open item, and an open item silently
absent is a lint failure.**

This is the planning linter's discharge discipline for open questions, lifted to the pipeline
level. That rule exists because a question that is merely written down is a question that gets
forgotten — a later document which simply does not mention it reads exactly like a document
that resolved it, and nobody can tell the difference from the outside.

Applied here, it is the only mechanism under which an open defect provably cannot vanish
between runs. Without it, a defect the owner answered `fix-the-code` in March is a red test in
a plan nobody re-reads, and the next assessment of the repository has no obligation to notice
it at all.

## The three dispositions

There is no fourth, and in particular no "still investigating".

| Disposition | Means | Evidence looks like |
|---|---|---|
| `confirmed` | Still true, unchanged | "The parser still ignores the locale separator; `ledger/money.py:12` is unchanged since `1d9f8e2`." |
| `updated` | Changed, and here is how | "The function was rewritten in `4a2b1c9`. It now reads the separator from `locale.localeconv()`; the claim's second half about grouping characters is still unimplemented." |
| `contested` | This item is wrong or no longer meaningful | "PF-04 was derived from three stale items in one run. All three targeted a module deleted in `9c14d02`, so the staleness measure it recorded is about a module that no longer exists." |

**All three carry evidence, and `confirmed` needs it most rather than least.** It is the
disposition that costs nothing to write and asserts the most: that somebody looked and the item
is still true. An unevidenced `confirmed` is indistinguishable from not having looked, which is
the exact state the rule exists to make visible.

## Where it lives

In the assessment's machine-readable index, as a `reconciliation` array:

```json
"reconciliation": [
  {
    "item": "DF-1",
    "kind": "defect",
    "disposition": "confirmed",
    "evidence": "ledger/money.py:12 is byte-identical to the version DF-1 was raised against; the red test still fails for the same reason."
  }
]
```

The prose section 13 of the report, "Reconciliation with the run ledger", says the same thing
for a human reader. The section is absent entirely when there is no ledger, which is why the
two reports written before stage four existed remain valid.

## Version routing

The `reconciliation` array arrives at index schema version 1.2. An older index is **not
malformed** — it predates the ledger — so `reconcile.py` routes it to a narrow backfill rather
than refusing it, exactly as a 1.0 index is routed today for its missing testability section.

The backfill is bounded and it re-measures nothing: read the ledger's open items, write one
entry per item with its disposition and evidence, set the version. It is not a re-assessment.

## Running it

```bash
python3 <test-reporting>/scripts/reconcile.py docs/test-ledger.json docs/test-assessment.md
python3 <test-assessment>/scripts/check_index.py docs/test-assessment.md --ledger docs/test-ledger.json
```

The two run the same comparison; the second is how it reaches the assessment's own gate.
`reconcile.py` lives in the reporting skill and is imported by the assessment skill, which is
the only place in this suite where a later stage's code runs inside an earlier one. The
alternative was a second implementation of the same rule, and a second implementation is a
second opinion about what the rule says. The dependency is one-directional and optional: only
`--ledger` reaches for it, and when the reporting skill is not installed that flag says so
rather than failing obscurely.

## The obligation on stage two is narrower, on purpose

R-7.3 obligates the planner to **consistency** with the ledger, not to itemised discharge:

- a work item whose footprint touches a file carrying an open defect names that defect in a
  `known-defects` field;
- a claim duplicating one the ledger already records at `cited` or `ratified` authority is
  reported, because re-deriving it as new work counts the same assertion twice.

Two rules, both narrow. Section 11 of the requirements defers the question of whether the
planner should be bound as strictly as the assessment, until a real multi-run sequence shows
where planner-side drops actually occur. Guessing at that now would produce a rule shaped by
nothing.

The asymmetry is also principled rather than only cautious. The assessment is where a
repository's state is established, so an item absent from it has been asserted not to exist. A
plan is a proposal about future work, and there are legitimate reasons to plan nothing about an
open defect — it is somebody else's to fix, or it is scheduled for a later cycle. What is never
legitimate is planning work *on top of* an open defect without naming it, because the executor
would then write tests in a file where something is already known to be broken and have no way
to know.

## What this costs, and why it is worth paying

Every assessment after the first one carries an obligation that grows with the ledger. A
repository with fifteen open items needs fifteen reconciliation entries, each with evidence,
before its assessment can pass lint.

That is the intended cost. R-7.4 is the other half of the bargain: reconciliation converts
re-assessment from a rebuild into a diff. An assessment that has reconciled every open item may
inherit its unchanged conclusions with their prior evidence cited, rather than re-deriving the
whole map — so the fifteen entries replace work rather than adding to it.

The pressure this creates is the right pressure. Fifteen open items is a repository carrying
fifteen unresolved decisions, and the assessment being expensive is that fact becoming visible
rather than a problem the tooling introduced. The remedy is closing them, and closing one is
one command.

# Slice Construction

A **slice** is an ordered group of work items that takes one coherent target area all the way
from its current state to verified unit tests. Slices are vertical: one area carried to
completion before the next begins, rather than one kind of work performed across the whole
repository.

The alternative — all the characterization tests, then all the seams, then all the unit tests
— produces a plan with no finishable intermediate state. Stop it halfway and you have a
repository full of scaffolding and no verified behavior. Stop a vertical plan halfway and you
have some areas genuinely done.

## The grouping axis

Group by **target area**, meaning what the assessment's findings and recommendations are
about, not by file type or by work type. `partition.py` already chose between a per-finding
and a per-module split for the claims fan-out, and its choice is usually the right slice
boundary too — the same collision counts that make one axis better for reading make it better
for slicing.

Deviate from the partition's axis when a finding's work naturally splits along a different
line. One real case: a coverage-measurement finding whose work divides into making the
problem visible (setting the collection scope, which is one small change with a large and
alarming consequence) and then acting on what becomes visible (writing tests for the code that
was never measured). Those are one finding and two slices, because the first has to land, be
communicated, and be absorbed before the second means anything.

## Sizing

R-8.4 says a slice fits a single working session with a clean commit boundary. Concretely:

| Bound | Value | Why |
|---|---|---|
| Claims per slice | 8–25 | Below eight, the slice is not worth its own commit boundary. Above twenty-five, its review is no longer one sitting |
| Slices per plan | at most 8 | Beyond that the plan is describing a programme rather than a piece of work, and the value line is too low |
| Items per slice | roughly 2–6 | One item is not a slice. More than six and the dependency order inside it stops being obvious |
| Effort per slice | one session | Sum the items' `effort`. This is why `effort` carries a unit |

Those bounds also give the claim budget: eight slices of twenty-five is two hundred claims,
which is what `merge_claims.py` checks in Gate B.

**Two hundred claims is a long review sitting and not an impossible one.** It is worth being
clear about this, because the arithmetic invites a wrong estimate. Claims do not attach to
every function above the value line; they attach to **planned work**, which the value line and
the target proposal bound. One real repository with no tests at all comes out at forty-eight
claims across seven slices. A plan that projected thousands of claims has set its value line
far too low, and the answer is to raise the line and record the narrower scope — not to
delegate ratification, and not to trim the list until it fits.

When a slice runs over, split it by module rather than by work type. Two slices each carrying
characterization, seam, and tests for half the area are both vertical. Two slices, one holding
all the seams and one all the tests, are not.

## Slice zero

Mandatory, first, and containing only infrastructure. It carries no behavioral claims.

Its purpose is that the first coverage number the plan produces is already the effective one:
the framework is installed, the coverage provider is configured, and the assessment's
exclusion list is in the tool's own configuration. Without it, every coverage delta in the
plan is stated against a baseline that a later change invalidates.

### When a test framework already exists

R-8.2 as originally written assumes none does — "install the test framework, configure the
coverage provider" — which is meaningless for a repository with a thousand passing tests.

Slice zero's first item then **degrades to verify-and-baseline**:

1. Confirm the suite runs and record what it reports.
2. Write the assessment's exclusion list into the coverage configuration.
3. Record the resulting number as the plan's baseline.

The slice is not skipped. Skipping it would leave the plan's deltas stated against a
denominator that step 2 changes, and a delta against a moving denominator is not a check.

Its completion check is that the suite runs and produces a coverage report — the same shape as
the empty-run check on a greenfield repository, against a suite that is not empty.

### Shared groundwork

R-8.3: groundwork that several slices need — a fixture directory, a shared mock helper, a test
setup file — is **its own item that the dependent slices reference**, so it happens once
rather than once per slice. Put it in slice zero when everything needs it, or in the first
slice that needs it with the others depending on that slice.

Mark it `global-effect: true` if it changes behavior beyond the files it edits. A shared mock
helper usually does.

## Ordering

R-8.5: slice order follows the assessment's risk ranking. A slice's severity is the severity
of its most severe item.

**Two deviations are permitted**, and each carries a justification.

### Deviation 1 — pulled forward for a seam

A slice moves earlier than its risk position because a later, higher-risk slice depends on its
seam. Record `deviation: {kind: pulled-forward-for-seam, justification: ...}` on the slice
that moved.

### Deviation 2 — a fully blocked slice is demoted

Every item in the slice is `blocked-on-decision`. Record
`deviation: {kind: demoted-fully-blocked, justification: ...}` on the demoted slice.

This second deviation was added because R-8.5's single permitted deviation contradicts R-6.4
and fires on the first real example. R-6.4 says an unresolved escalation degrades scope and
never blocks the run. But risk order puts the highest-ranked finding first, and in one real
repository that finding is fully blocked on a fixture decision — so risk order alone produces
a plan whose first step after slice zero is a slice nobody can execute. Under the original
rule the planner has to either violate R-8.5 without recording it or leave the plan starting
with a dead slice.

The linter checks that a slice claiming this deviation really is fully blocked. A partly
executable slice is not fully blocked, and demoting it is not the permitted deviation — it is
just reordering.

**A demoted slice returns to its risk position when its blocker is answered.** Say so in the
justification, so the owner knows the demotion is a consequence of their open question rather
than a judgment about the work.

## Dependencies

Inside a slice, items run in dependency order: characterization first where the assessment
required one, then the seam, then the unit tests asserting that area's claims.

Between slices, every slice except zero declares `depends-on: [S0]` at minimum. The wave
schedule is computed from these edges, so an edge that exists in your head and not in the file
lets two slices be scheduled concurrently that should not be.

**An item dependency that crosses slices is a slice dependency.** If `WI-07` in `S3` depends
on `WI-04` in `S1`, then `S3` depends on `S1` and must say so. The linter checks this, because
the wave computation reads slice edges and would otherwise put both in the same wave.

### A claim can only be asserted where its target is reachable

The linter resolves every claim's `path:line` locations against the assessment's
function-granularity testability data and requires one of these to hold for each:

- the target is classified `testable-as-is`; or
- the target is `export-only` or `needs-seam`, **and** the item performing that seam is inside
  the asserting item's transitive `depends-on`.

A claim listed in some seam's `claims-enabled` must additionally be asserted only by items
that depend on that seam — **even where a weaker assertion might be possible without it**. A
plan that records an enabling relationship it does not schedule is stating something untrue
about itself, and the weaker assertion it might get away with is not the assertion the claim
describes.

A claim against a target classified `integration-only` or `excluded` fails outright. No seam
is coming for the first, and the second is outside the suite by the assessment's own
exclusion list.

**Two shapes this catches, both produced by this planner in practice:**

1. **A claim asserted through an extraction nothing performs.** The claim describes behavior
   that only becomes reachable after a seam, and no work item does the seam. The test cannot
   be written as described, and the failure surfaces during execution rather than planning.
2. **A claim asserted before its seam runs.** The seam exists as an item, but it sits in the
   final slice while the assertion sits in an early one. Risk order put them that way and
   nothing checked the ordering against reachability.

**When the enabling item lands in a later slice than the assertion,** you have three moves,
in order of preference: move the asserting item into a slice after the seam's; pull the seam
forward, which is deviation 1 above and carries its justification; or split the claim, keeping
the part assertable today and moving the rest. Adding a dependency edge that runs backwards
against slice order is not one of them — the linter's slice-edge rule rejects it, and it would
make the wave schedule wrong.

## Waves

Computed, not authored:

```bash
python3 <skill>/scripts/plan_lint.py <plan> --waves
```

A wave is a set of slices with pairwise disjoint footprints and no dependency edges between
them. The computation walks slices in ascending identifier order at every step, so the same
plan always produces the same schedule. Any slice carrying an item with `global-effect: true`
takes a wave to itself.

Recorded as information, not instruction (R-10.2). Execution is sequential in this version.
The point of recording it is that enabling concurrency later becomes a change to the executor
alone, once stage four has measured whether declared footprints match actual ones.

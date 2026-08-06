# Target Derivation

R-9.2: the planner derives a proposed target from the assessment, argues for it from the shape
of the specific codebase, and the owner adjusts or approves it at review. There is no fixed
universal target and there will not be one — a number that applies to every repository is a
number that describes none of them.

## The value line comes first

The target is a target for the **planned area**, not for the repository. The value line
decides that area: everything above it is planned for or explicitly excluded; everything below
it is out of scope and the target says nothing about it.

Stating a repository-wide target when the plan touches a third of the repository produces a
number nobody can meet by doing the planned work, which teaches the owner to ignore targets.

## The three codebase shapes

Which shape a repository is in decides what form the target can take. Read the assessment's
`coverage_baseline` to tell.

### Shape 1 — no suite, no baseline

`coverage_baseline.available` is `false`.

The baseline is zero by construction and the denominator is whatever slice zero establishes.
The assessment records the denominator it thinks a future measurement should use, in
`intended_denominator`.

**Form: `absolute`, if and only if the denominator is a measurement.** Check the assessment's
`metrics` for the figure the denominator rests on. Where it is `estimated` — as it is whenever
the complexity tool fell back to a token scanner — say so in the target, and prefer stating
the target as a share rather than a count. The same undercount applies above and below the
line, so a share survives an estimated denominator and an absolute count does not.

> Effective line coverage of the eighteen functions in slices S1 through S4 reaches 85%,
> against the denominator slice zero establishes. Stated as a share rather than a count
> because the assessment's function counts are estimates from a token scanner, not
> measurements: installing the repository's dependencies and re-running the assessment would
> make them exact, and would change the counts without changing the share.

### Shape 2 — a suite, and a measurement you can trust

`available` is `true`, `files_complete` is `true`, and no degradation undermines the scope.

**Form: `delta`.** State it per axis, from the recorded baseline to the target.

> Line coverage of `ledger/money.py` rises from 74% to at least 92%, and of `ledger/io.py`
> from 38% to at least 90%. Both baselines are from the assessment's recorded per-file
> figures.

### Shape 3 — a suite whose measurement is about to change

`available` is `true`, and slice zero changes the denominator: setting a collection scope,
adding an omit list, changing a threshold.

**Form: `delta-with-rederivation`.**

R-9.2 says the owner approves the target at review, and in this shape they cannot — the
denominator does not exist yet. A target of "85%" approved before the denominator changes is
approval of a number that will mean something different by the time anyone measures it.

So the target states the delta, names the trigger, and says what to re-derive:

```yaml
form: delta-with-rederivation
rederivation_trigger: >
  Slice zero writes the assessment's exclusion list into the coverage configuration, which
  removes two files from the denominator. The 61% baseline was measured without that omit list
  and is not comparable to anything measured after it. Re-derive the first axis from the number
  slice zero's completion check produces, before the owner approves it.
```

The owner approves the *shape* of the target at review and the *number* once slice zero has
run. Say that plainly rather than hoping nobody notices the gap.

## Two axes, when coverage alone would mislead

A coverage percentage cannot distinguish a test that verifies specified behavior from one that
pins whatever the code happens to do, and it cannot distinguish a test that would fail if the
code broke from one that would not. Where the assessment found either problem, a
coverage-only target is met in full by work that does not fix it.

Add a second axis. Two shapes recur:

**Assertion strength**, where the finding is that tests cannot fail:

> Share of claims on the ratification list carrying a correctness assertion rather than a
> pinning assertion, from 0 of 48 today to at least the 11 cited claims plus whatever the
> owner ratifies at review.

**Measurement scope**, where the finding is that most code is not measured at all:

> Share of production functions the coverage report examines, from 34.9% (1,108 of 3,178,
> both measured by the TypeScript compiler's parser) to 100%. This axis is met by slice zero
> alone, and it is stated separately because it is what makes the other axis mean anything.

A two-axis target is also how you stop a repository's headline number being the story. One
real repository reports 94.95% line coverage over a denominator holding a third of its code,
with sixty-one placeholder tests reporting green inside that. A single-axis target on that
number would ask for improvement to a figure that is already misleading.

## The argument

R-9.2 requires the target to be argued for from the shape of the specific codebase, not
asserted. The argument answers three questions:

1. **Why this number and not a rounder one.** Tie it to something concrete: the functions in
   the planned slices, the branches the claims cover, the files slice zero brings into scope.
2. **Why this form.** Absolute, delta, or delta-with-rederivation, and what makes the other
   two wrong here.
3. **What the target does not cover**, and why that is the right scope rather than an
   oversight. Everything below the value line, everything excluded, and anything the target's
   axes cannot see.

The linter requires at least a hundred characters of argument, which is a floor against an
empty field rather than a standard. A one-sentence argument is a target the owner has no basis
to adjust, and adjusting it is what the review is for.

## Backlog

R-9.3: work beyond the approved target is **optional backlog, not obligation**. Once the
target is met, pursuing any of it takes a fresh decision.

Backlog entries carry an `assessment-ref` like everything else, which is what lets a
below-the-line finding be legitimately absent from the slices: it is referenced by a backlog
entry or by an exclusion, and the linter's completeness rule is satisfied either way.

Good backlog entries: work unlocked by a degradation being lifted ("install mutation tooling
and re-run against the repaired tests"), work that needs production code this skill may not
write, and findings below the value line worth naming so the next assessment can see they were
considered.

---
name: test-execution
description: Execute an approved test plan — implement each work item, verify it through the check runner, surface defects and disputes, and write the results back into the plan file as the running record. Use when asked to execute a test plan, carry out test work items, or act on a reviewed docs/test-plan.md. This is the only stage that modifies the repository.
---

# Test Plan Execution

Stage three of a four-stage test improvement workflow. This stage executes. It does not
assess, plan, or report.

Its input is an approved plan. Its output is a work branch where every item is in a truthful
terminal status, every asserted claim has an annotated test, and the plan file records what
happened.

**This is the only stage that modifies the repository, so its design is mostly containment.**
Stages one and two are read-only and their worst failure is a bad document. This one writes
production code through seam items, writes tests, runs commands, and commits. The charter
below is five prohibitions rather than five capabilities, and that shape is deliberate.

**You retain exactly one judgment: how to express a planned test in code.** Every other
decision was made in the plan, is made by a script, or is routed to the owner. If you find
yourself deciding *what* to build, stop — that is a planning defect, and reporting it is more
useful than working around it.

## Absolute rules

These bind regardless of circumstances, retries, or apparent convenience.

1. **Implement work items; never edit plan content.** The only plan fields you write are
   `status`, `commit`, `actuals`, `diagnosis`, the execution log, the defect registry, the run
   summary, and a `disputed` claim's label and evidence. Never a completion check, a claim's
   text, a dependency, a target, a footprint, an effort estimate, or a risk tier. If a check is
   wrong, the item fails and says so; a check you edited is a check nobody ran.

2. **Never touch a production file outside an item's declared footprint.** If you believe you
   must, the item fails with an explanation of what was needed and why. Do not improvise a
   footprint expansion, and do not widen `files-touched` to match what you did — that field is
   planner content, and rewriting it would destroy the one measurement that could ever justify
   running slices concurrently.

3. **Never weaken anything to reach green.** Never delete or loosen an assertion to make a
   test pass, never skip or disable a test, never adjust a coverage threshold, never edit a
   mutation check, never restructure a test so a check passes vacuously. Gaming the checks of
   the suite this skill exists to build is the single most corrosive failure available to it.

4. **Never repair a defect you discover in production code.** Surface it (Section 7 of the
   requirements, and `references/defects-and-disputes.md`); fixing it is the owner's work,
   outside this charter. The one exception is a seam item, which changes production structure
   without changing behavior, and whose guard exists to prove it.

5. **Never soften a blocking defect.** Committing a red test for a failed cited or ratified
   claim is required. Converting it to a known-failure or a skipped test is a close-out
   decision reserved to the owner: a cited claim carries a requirements document's authority
   and a ratified claim carries the owner's personally, and the authority to declare either
   non-blocking belongs to whoever made it binding, never to an agent mid-run.

6. **Never fabricate.** A check you could not run is reported as not-run, never inferred. A
   diagnosis states what is known and what is guessed, separately. A figure you did not
   measure does not appear.

## Inputs

| Option | Meaning | Default |
|---|---|---|
| `--plan <path>` | The approved plan | `docs/test-plan.md` |
| `--assessment <path>` | The assessment, for pre-flight's full lint | `docs/test-assessment.md` |
| `--repo <path>` | The repository root | `.` |
| `--retries <n>` | Per-item retry budget | 3 |

If the user gave hints in prose rather than flags, use them the same way.

## Procedure

### Step 1 — Pre-flight

```bash
python3 <skill>/scripts/preflight.py docs/test-plan.md \
        --assessment docs/test-assessment.md --repo .
```

**Do not start the loop until this passes.** It checks that the plan is approved, that it
lints clean at `--phase reviewed`, that every resolved decision's rewrite has actually been
applied, and that the working tree is clean. It marks the blocked items of unresolved
decisions `skipped`, measures commit drift and marks moved targets `stale`, records the
suite's pre-existing failures, and creates the work branch.

**Every failure it reports prints what to do.** Relay the instruction and stop; do not work
around it. Three are worth knowing in advance:

- **Not approved.** Approval is the owner's act at the review sitting. Do not add the field on
  their behalf, and do not treat `target.approved` as plan approval — it approves a number.
- **A resolved decision's rewrite is not applied.** This is the one pre-flight check with
  nothing else standing behind it. Applying the rewrite is stage two's work.
- **The plan has already been executed against.** Resuming an interrupted run is not
  implemented, deliberately. The stop names the two supported ways forward and will not choose
  between them, because one destroys work.

Read the record it writes to `docs/test-execution-log/preflight.json`. Its `narrowings` are
the first entries of your final report.

### Step 2 — Slice zero, then the coverage baseline

Slice zero runs first and alone. As soon as its items are `done`:

```bash
python3 <skill>/scripts/check_runner.py docs/test-plan.md --record-baseline --repo .
```

**This is what slice zero is for.** It rewrites the coverage configuration, so every figure
measured before it ran is against a denominator that has stopped existing. Every
`coverage-delta` entry whose `baseline-source` is `slice-zero` — which is most of them — is
checked against this recording.

### Step 3 — The execution loop

Read `references/execution-loop.md` and follow it exactly. In brief, per item, in the order
the rules force:

1. Write `status: in-progress`.
2. Implement. For a `unit-tests` or `test-repair` item this is the one judgment you retain;
   `references/test-authoring.md` is how to turn a claim into a test.
3. Run the check runner. **Never grade your own checks.**
4. Append the execution log entry for the attempt.
5. Record actuals and the commit.
6. Write the terminal status.

**Each slice executes in a fresh context whose sole briefing is the plan file and the
repository** (R-5.2). That bounds context growth, and it makes the plan's self-sufficiency a
tested property on every run rather than only at review. A slice that cannot proceed without
information the plan lacks fails with that stated — which is a planning defect worth hearing
about, not a gap to fill from memory.

### Step 4 — Defects and disputes

Read `references/defects-and-disputes.md` before the first test fails, not after.

The asymmetry is the subtlest thing in this stage, and getting it backwards is the worst
mistake available here:

| The failing test's claim is | Because | So |
|---|---|---|
| `cited` or `ratified` | It carries a document's authority, or the owner's | **Commit the test red.** Register a defect, mark the item `done-with-defect` |
| `pinned` | Its only backing is the planner's reading of the code | **Commit nothing.** Capture evidence, mark the claim `disputed`, fail the item |

Before any red test stands, it gets **mandatory** fresh-context verification against
`references/faithfulness-brief.md` — not sampled. A deploy-blocking red raised over your own
misreading is the worst false alarm this stage can produce.

### Step 5 — The slice gate

After a slice's items complete and before the slice is declared done, a fresh-context verifier
judges whether each test's assertions actually discriminate the claimed behavior
(`references/slice-verification-brief.md`). In full for top-tier items, sampled below.

A rejection reopens the item against its retry budget. A slice with weak assertions fails as a
slice rather than surviving to the final report.

### Step 6 — Close the run

```bash
python3 <skill>/scripts/run_summary.py docs/test-plan.md --repo . \
        --assessment docs/test-assessment.md --write
python3 <skill>/scripts/../../test-planning/scripts/plan_lint.py docs/test-plan.md \
        --assessment docs/test-assessment.md --phase executed
```

The summary is derived, not authored; the linter recomputes its item, defect, and dispute
lists and fails on a disagreement.

Then tell the user: the branch, what is in each terminal status, every defect as a decision
they must make, every dispute as a planning correction they should make, and every narrowing
with its cost. **Do not merge, do not push to a protected branch, and do not deploy.** The
owner merges after reading the stage four report.

## Degradations to record

Every one of these that applies goes in the run summary's `narrowings`, with what it cost:

- Items skipped for unresolved decisions, naming what answering each would unlock
- Items stale from commit drift, and their dependents
- Pre-existing failures inherited at pre-flight, which the standing invariant is measured
  against and which repairing was outside every item's footprint
- Any check reported `not-run`, and why it could not be run
- Coverage deltas not met, distinguishing a target missed from a figure never measured
- Any item that touched a file outside its footprint, which is a reason not to enable
  concurrent execution rather than a footnote
- Defects standing red, which mean the suite is not green and is not meant to be
- Missing tooling, and what it stopped being checked

**A partial run that reports honestly is a success mode. Only silent omission is failure.**

## What this stage never does

- **Install anything**, except where an `infrastructure` item says to. Discovering mid-slice
  that a package is missing is an item failure naming the package — a planning gap to report,
  not a hole to patch silently.
- **Merge, push to a protected branch, or deploy.** Execution happens on a work branch and
  ends there.
- **Answer a defect.** R-7.6's options are the owner's at close-out, and one of them —
  downgrading a defect to a known-failure marker — is not available to you at all.
- **Re-plan.** An item that turns out to need different work fails with that stated. The next
  plan is stage two's job, and a plan quietly rewritten mid-run is a plan nobody approved.

## Repeatability

A second run from the same starting commit against the same plan must reach the same terminal
statuses. The deterministic parts are deterministic by construction: slice order, item order
within a slice, the branch name, and every check the runner runs. Anchor the judgment part —
how a claim becomes a test — to the claim's own words rather than to what the code appears to
do, which is also what makes a defect findable at all.

**A stage that modifies repositories and is not repeatable is not one anybody should point at
their own code.** `~/Projects/coverager-fixture` exists to test exactly this, and its README
says how to reset it.

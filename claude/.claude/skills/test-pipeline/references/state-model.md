# The state model, normatively

Every position the pipeline can be in, how it is detected, and what its brief must contain.
`scripts/pipeline_state.py` implements this file; where the two disagree, this file is the
specification and the script is the bug.

**State is derived and never stored** (R-4.2). There is no state file, no manifest, and no
memory of prior invocations. This is the pipeline's own doctrine — paired records drift —
applied to the orchestrator itself. The artifacts are the state, so the orchestrator can never
disagree with them, and a run survives an interruption, a machine change, or a months-long gap
between gate and resumption with no resumption machinery at all.

## The artifacts state is read from

| Artifact | Default location | Written by |
|---|---|---|
| The assessment report and its index | `docs/test-assessment.md` | stage one |
| The plan, at one of four phases | `docs/test-plan.md` | stage two, then written back into by three and four |
| The close-out decision sheet | `docs/test-closeout.md` | stage four, answered by the owner |
| The narrative report | `docs/test-report.md` | stage four |
| The run ledger | `docs/test-ledger.json` | stage four, and only through `ledger.py` |

The orchestrator inherits these locations rather than choosing them. A fifth opinion about
where the plan lives would be a fifth place to update when it moves.

## The positions

Detection walks **forward** through the pipeline and stops at the first precondition that does
not hold. Forward rather than backward, because that is what a ratchet is: the position is the
first place the run cannot advance from, and asking the questions in pipeline order is what
makes the answer the same every time (R-4.3).

### `not-a-repository`

**Detected when** `git rev-parse --git-dir` fails in the target directory.

**Next action.** Stop and tell the owner. Every stage past the assessment records commits,
measures drift against them, and works on a branch, so there is nothing the pipeline can do
here.

**The brief states** that the pipeline needs a git repository, and that the two ways forward
are to initialise one or to point the pipeline at the repository root.

### `no-assessment`

**Detected when** the report file is absent.

**Next action.** Invoke `test-assessment` against the repository.

**The brief states** which mode stage one will run in and why — reconciliation when
`docs/test-ledger.json` exists, fresh when it does not (R-5.3). **The orchestrator passes no
mode flag and has none to pass.** Stage one's Step 7d reconciles the ledger and is skipped
entirely when the file is absent, so the routing happens inside the stage. The obligation here
is narration, and building a mechanism for it would be a second opinion about a decision the
stage already makes correctly.

### `assessment-invalid`

**Detected when** any of three checks rejects the report: `check_index.py` (with `--ledger`
when the repository has one), `read_assessment.py`, or `reconcile.py`.

Three checks rather than one, because they fail on different things. The index checker
validates the index's schema, its identifier patterns, its closed enumerations, the acyclicity
of its dependency graph, and the correspondence between every identifier in the index and every
identifier in the prose. The planner's reader is the consumer's own hard stop and knows about
schema versions the checker does not route on. The reconciler answers R-7.2 — whether every
open ledger item is confirmed, updated, or contested — which is **the only mechanism under
which an open defect provably cannot vanish between runs**, because a dropped item leaves no
trace to catch.

**Next action.** Relay the failing check's diagnosis verbatim and stop.

**The brief states** the diagnosis in the checker's own words, unedited, and that the remedy is
stage one's *backfill* mode rather than a re-assessment: nothing is re-measured. See
`failure-handling.md` for why relaying verbatim is a rule rather than a style preference.

### `no-plan`

**Detected when** the plan file is absent and the assessment is valid.

**Next action.** Invoke `test-planning`, giving it the assessment path and the repository.

**The brief states** the value line the assessment suggests, and every degradation the
assessment declared — including a verification pass recorded as `skipped`, which advances the
pipeline and is carried forward as a degradation rather than treated as a stop (R-6.2).

### `plan-invalid`

**Detected when** the plan fails the linter at the phase its own content places it in, and the
plan is not merely awaiting approval. Concretely: no approval recorded, and the plan lints
clean at neither `--phase planned` nor `--phase reviewed`.

**Two phases rather than one, and the reason is a legal state that would otherwise be
misreported.** A plan the owner has begun reviewing — resolutions or ratifications written in,
approval not yet given — fails `--phase planned` by design, because those are fields a freshly
written plan may not carry. Asking only about the planned phase would report a correctly
part-reviewed plan as broken.

**Next action.** Relay the lint output verbatim. Which stage repairs it depends on the phase
that failed, and the difference matters: a plan that fails at `planned` or `reviewed` is stage
two's to repair, one that fails at `executed` is stage three's writeback being wrong, and one
that fails at `closed` is stage four's. **Telling the owner to re-run planning on a failed
executed-phase lint would be advice that destroys the record of a run that already happened.**

**The brief states** the lint output and the stage that owns the phase.

### `awaiting-approval` — **gate one**

**Detected when** the plan lints clean at `--phase planned` or `--phase reviewed`, and
`plan-meta.approved` is absent.

**Next action.** Write the gate one brief and stop.

**Gate one always stops.** Plan approval is the owner's act and nothing derives it, so every
fresh run reaches this gate and halts. That is not a limitation to be worked around; it is the
acceptance criterion.

**The brief contains** what `gate_brief.py --gate 1` extracts, rendered in plain language:
every escalation and decision with its options and their consequences, which work items each
option rewrites, the ratification list's size with an honest estimate of the sitting (R-10.3),
the target proposal, and — for each of these — where the answer is recorded and what recording
it looks like. `gate-briefs.md` specifies the composition, including the one sentence a brief
may never contain.

### `ready-to-execute`

**Detected when** `plan-meta.approved` is recorded.

**That single condition is the whole precondition, and the line it draws governs the rest of
this file.** Approval is a *gate*: a question about whether the owner has acted, which is the
orchestrator's own business and the reason it exists. Everything else at this transition is a
*validation*: a question about whether an artifact is well-formed, which belongs to the stage
that owns the artifact. The `--phase reviewed` lint, the applied option rewrites, the skipped
items of unresolved decisions, the clean working tree, the commit drift — all five are
validations, and all five are checks `preflight.py` already performs.

**There is no `approval-incomplete` position.** An approved plan that fails `--phase reviewed`,
or whose option rewrites were never applied, is `ready-to-execute` as far as the orchestrator
is concerned, and pre-flight refuses it and says why. Two reasons, and the second is the
stronger one:

1. Adding a position here would be the orchestrator duplicating a validator, which the preamble
   to Section 6 of the requirements forbids.
2. Pre-flight's rewrite check has **nothing else standing behind it** — its own comment says so
   in plain terms. A second implementation would therefore not be a redundant opinion but a
   *competing* one, and the two would drift with nothing in the suite positioned to notice.

The orchestrator does not run the `--phase reviewed` lint here even to report it. Running a
validation it does not act on is how an orchestrator acquires opinions about artifacts it is
not supposed to read (R-7.2), and the owner would then hold two verdicts on one plan from two
sources with no rule saying which wins.

**Next action.** Invoke `test-execution`. Relay whatever pre-flight says.

### `execution-incomplete`

**Detected when** the plan is approved, work items carry statuses only the executor writes, and
the plan holds no run-summary block.

**Approval is part of the recognition test rather than an incidental extra condition.**
Pre-flight refuses to start on an unapproved plan, so executor-written statuses on one cannot be
the residue of an interrupted run — no run could have begun. They are a malformed plan, which
is `plan-invalid` with a different remedy. Without this clause a plan carrying one illegal
status reports as an interrupted run, and the owner is sent to resolve a run that never
happened.

The planner may write `pending` and `blocked-on-decision`. Every other value in the status
vocabulary is the executor's. Asking merely whether an item carries *a* status reports every
freshly written plan as an interrupted run, because a planned item carries `status: pending`.

**Next action.** Relay stage three's stop and **choose nothing**.

**This is the one position whose next action is to add nothing at all.** Resuming an
interrupted run is not implemented, deliberately. Pre-flight names the two supported ways
forward and refuses to pick between them **because one of them destroys work**. That choice is
the owner's and the orchestrator is forbidden from making it on their behalf (R-9.2). This is
R-8.1 working as specified rather than a gap in it.

### `executed`

**Detected when** the run-summary block is present and the plan lints clean at
`--phase executed`.

**Next action.** Invoke `test-reporting` for its **pre-gate segment**: read the run and write
the close-out decision sheet.

**The brief states** the terminal statuses, the defects awaiting decision, and — when the run
was partial — that it was, with what is missing. **A partial run proceeds to reporting**
(R-6.5): partial-and-honest is a pipeline success mode, not a failure to be repaired first.

`run_record.py --no-suite` is run here for its cross-checks, and **its failures are notes
rather than blockers**. Each one is a pipeline finding about stage three that stage four
records and that degrades the report's stated confidence. Editing the run summary to make a
check pass destroys the only evidence that the pipeline has a gap.

### `awaiting-closeout` — **gate two**

**Detected when** the close-out sheet exists and stage four's own `validate_answers` reports a
problem with it.

**Judged by stage four's validator rather than by anything here**, and strictly: a missing
decider, a rationale under thirty characters, a `requirement-wrong` with no amendment flag, or
an automated-looking name against a `downgrade` all fail. Re-implementing any of that would be
a second standard for what an answered gate is, and the orchestrator would let through a sheet
stage four is about to refuse.

**Next action.** Write the gate two brief and stop.

**The brief states** how many defects are unanswered, points at the sheet rather than
re-describing the defects in it, and says that the gate is one sitting — a partially answered
sheet is refused rather than half-applied.

### `closeout-answered`

**Detected when** the sheet exists and every defect on it carries a complete answer, **or the
sheet records an empty gate**.

**The empty gate does not stop the ratchet and is still applied.** When a run registered no
defects, `closeout.py --brief` writes a sheet whose body is a `No defects` section. The run does
not close by skipping the gate; it closes by running `--apply` over the empty sheet, which is
what writes the records the closed phase requires. So the ratchet passes through this position
without halting and invokes the post-gate segment in the same invocation.

This position is also reached from the far side, when the answers are applied and something
later in stage four has not finished: no report, a report that does not trace, or a run the
ledger does not name. Each of those keeps the same position and changes only the blocking
condition, because in every case the next action is the same stage doing the next thing in its
own procedure.

**Next action.** Invoke `test-reporting` for its **post-gate segment**.

### `closed`

**Detected when** all four hold: the plan lints clean at `--phase closed`, the report exists,
`trace_report.py` passes against it, and the ledger holds a run entry naming this run.

**Next action.** State that the branch is settled, say what each close-out decision did to it,
say what the ledger now holds open, and hand the owner the merge instruction. **The
orchestrator never merges** (R-9.4).

## The two signals that are not positions

Both are computed alongside the position rather than as positions of their own, because either
can be true at several positions at once.

### The drift flag (R-8.3)

Repository drift is **surfaced, never adjudicated**. The state script compares the commits the
artifacts record and reports each disagreement with both values and the stage whose own
revalidation decides what it costs — because that stage has the authority to price it and the
orchestrator has no basis on which to call a drift harmless.

| Between | Decided by |
|---|---|
| The assessment's commit and the plan's `assessment_commit` | The planning stage's input checks |
| The assessment's commit and `HEAD` | Stage three's pre-flight, which marks moved targets `stale` |
| The run's base commit and `HEAD` | Stage four's run record, which measures a run from its base commit to its close commit |

**Two commit references agree when one is a prefix of the other.** The artifacts do not agree
about abbreviation — the assessment index records seven characters and the run record records
forty — and comparing them for equality would report drift on every repository that has none.

The third row exists because of a real defect. The R-4.2 commit check once measured to `HEAD`,
so the first ordinary thing an owner did on the branch after close-out made a finished record
report itself inconsistent. **A closed record describes the run, not the branch**, and the drift
flag has to say the same thing or it will contradict the record it is describing.

### The open-run flag (R-4.4)

A run is open when a plan file exists that either **no ledger entry names**, or that a ledger
entry names but which **does not lint clean at `--phase closed`**.

Derived from content rather than from file modification time. Modification time is not a
property of the work: a `git checkout` rewrites it on every file it restores, and copying a
repository resets it wholesale, so a recency test would report an open run on a repository whose
every run is closed.

**"Names" is answered two ways, and the fallback is not optional.** A ledger run entry carries a
`plan` field — and neither the fixture ledger nor `design-os`'s real one has it, because both
predate the field. A derivation that asked only that question would report an open run on the
one repository that has been through all four stages. The second question is the durable one:
the plan's own run-record block carries the close date and the close commit, which is exactly
what the ledger computes its `run_id` from, so the two match without either side storing a path.

Starting a new run while one is open requires the owner's explicit instruction, and the brief
states what the open run will orphan before that instruction is accepted.

## Idempotence is a tested property (R-4.3)

Two derivations against an unchanged repository produce the same diagnosis and propose the same
next action. `pipeline_state.py --selftest` asserts it position by position, comparing the two
diagnoses byte for byte.

**This is not a formality.** Several of the checks are subprocesses whose output is captured
into the diagnosis, and a check that reported a timestamp, a path that varied, or a set iterated
in hash order would produce two different diagnoses from one repository. The only way to see
that is to look.

# Invoking a stage

What is passed to a stage, how, and what its exit summary must yield back. R-7.1 and R-7.2.

## Every stage runs in a fresh context

**Each stage is invoked as a subagent** using the Agent tool with
`subagent_type: "general-purpose"`. This is the same idiom stage two's claims-derivation
fan-out already uses, and it is the only mechanism available here that gives R-7.1's fresh
context.

A fresh context is not an efficiency measure. It is what makes each stage's stated input
contract a *tested* property on every run rather than an assumption checked once at design
time. Stage three already relies on this within itself — each slice executes in a fresh context
whose sole briefing is the plan file and the repository, so a slice that cannot proceed without
information the plan lacks fails with that stated, which is a planning defect worth hearing
about rather than a gap to fill from memory. Invoking whole stages the same way extends that
property up one level.

## What is passed: locations, never content

**R-7.1: the orchestrator passes locations, never content, and never forwards its own
conversation into a stage.** A subagent's prompt names the skill to use, the artifact paths, and
the repository. Nothing else.

The prohibition on forwarding content is the load-bearing half. An orchestrator that pastes the
assessment's findings into the planner's prompt has given the planner a summary written by
something that is not allowed to have opinions about assessments, and the planner will plan
against the summary rather than against the report. The same failure at the next transition
gives the executor a plan nobody linted.

### The verbatim briefings

Use these as written, substituting only the paths.

**Stage one, assessment:**

```
Use the test-assessment skill against the repository at <repo>.

Write the report to <repo>/docs/test-assessment.md.

Report back: the report path, the mode it ran in, the value line it suggests, the
verification disposition it recorded, every degradation it declared, and whether the
machine-readable index validates under check_index.py.
```

**Stage two, planning:**

```
Use the test-planning skill against the repository at <repo>.

Its input is the assessment report at <repo>/docs/test-assessment.md. Write the plan to
<repo>/docs/test-plan.md.

Report back: the plan path, the number of slices, work items, and claims, how many claims
are pinned and how many cited, every escalation and decision it raised, the target it
proposes, and the plan's lint status at --phase planned.
```

**Stage three, execution:**

```
Use the test-execution skill against the repository at <repo>.

Its input is the approved plan at <repo>/docs/test-plan.md and the assessment at
<repo>/docs/test-assessment.md.

Report back: the work branch, every item's terminal status, every defect registered as a
decision the owner must make, every dispute, every narrowing with its cost, and the plan's
lint status at --phase executed.

If pre-flight refuses to start, report its message in full and stop. Do not work around it.
```

**Stage four, pre-gate segment:**

```
Use the test-reporting skill against the repository at <repo>, and run only Step 1 and the
first half of Step 2 of its procedure: check the install, read the run with run_record.py
--no-suite, and write the close-out decision sheet with closeout.py --brief.

Stop when the sheet at <repo>/docs/test-closeout.md is written. Do not run --apply, do not
assemble a report, and do not append the ledger.

Report back: the sheet path, how many defects it holds, every R-4.2 consistency check that
failed, and whether the gate is empty.
```

**Stage four, post-gate segment:**

```
Use the test-reporting skill against the repository at <repo>. The close-out sheet at
<repo>/docs/test-closeout.md is answered. Resume its procedure at the second half of Step 2
and run it through to the end of Step 6.

That is: closeout.py --apply --dry-run, then --apply; then the run record, the findings, and
the run record again; then assemble.py and the prose slots; then trace_report.py; then the
plain-language reader; then the ledger append and the closed-phase lint.

Report back: what each decision did to the branch, the report path, the tracer's verdict, the
plain-language reader's findings and whether they were acted on, what the ledger now holds
open, and the plan's lint status at --phase closed.
```

## Stage four is invoked in two segments

**Gate one sits between two stages; gate two sits inside one.** That asymmetry is the single
most consequential thing in this file, and it comes from stage four's own procedure rather than
from a choice made here.

Stage four holds the close-out gate at its **Step 2** — `closeout.py --brief` writes the sheet
and stops — and assembles the report at its **Step 4**, after the owner's answers have been
applied. That ordering is correct rather than incidental: **the report reports what the
close-out decisions did to the branch, so it cannot precede them.**

So the orchestrator enters stage four twice, with the owner's sitting between:

| Segment | Stage four steps | Ends at |
|---|---|---|
| Pre-gate | 1, and the first half of 2 | The sheet is written and the ratchet stops if it holds a defect |
| Post-gate | The second half of 2, through 6 | The run is closed and the ledger appended |

**An empty gate passes through without stopping.** When the run registered no defects, the
sheet's body is a `No defects` section, and the ratchet invokes the post-gate segment in the
same invocation. The run still closes by running `--apply` over the empty sheet — that is what
writes the records the closed phase requires. This is the path `design-os` proved end to end.

## What an exit summary must yield back (R-7.2)

The orchestrator consumes the state script's output and each stage's exit summary, **and does
not read the full artifacts**. So the summary has to carry everything the next brief needs, and
each briefing above names what that is.

An orchestrator that has read a two-thousand-line plan is an orchestrator tempted to have
opinions about it, and R-9.2 forbids it from having any. Where a gate brief needs something the
exit summary did not carry, the answer is `gate_brief.py`, which extracts a bounded set of facts
through the stages' own parser — not the orchestrator opening the plan.

## After every invocation: compare the checksums

Take a checksum set before invoking a stage and again after:

```bash
python3 <skill>/scripts/pipeline_state.py --repo . --checksums
```

**Every difference must be attributable to the stage that was invoked.** This is how R-9.1 —
never edit a stage artifact — becomes checkable rather than only asserted, and it is R-11's
acceptance criterion stated as a procedure. The set is printed and never stored (R-10.2): a
stored checksum file would be one more paired record to drift, which is the thing this pipeline
is built to avoid.

An artifact that changed and should not have is not a discrepancy to investigate later. It means
something wrote to a stage artifact outside that stage, and the run's record is no longer
trustworthy.

## Stage targeting does not relax anything (R-5.2)

The owner may ask for one stage explicitly — "run the assessment only", "re-run planning". A
targeted stage whose preconditions fail produces **the same diagnosis a full invocation would**.
Targeting chooses where to stop, never what to skip.

**Gate skipping does not exist in any mode**, and no sequence of owner instructions short of
amending the requirements produces it (R-9.3). "Just this once" is not an input the orchestrator
accepts.

---
name: test-pipeline
description: Advance a repository's test-improvement pipeline by one ratchet — derive where the run stands from the artifacts, carry it as far as preconditions allow, stop at the first human gate or failure, and say exactly what the owner must do next. Use when asked to advance, start, resume, or check the state of the four-stage test pipeline, or when the next step across assessment, planning, execution, and close-out is the question. It conducts the other four stages and performs none of their work.
---

# Test Pipeline Orchestration

Stage five of a five-stage workflow, and the only one whose subject is the other four. It
sequences, gates, routes, and narrates. It does not assess, plan, write tests, or report.

The mental model is one command meaning **advance the pipeline**. The owner invokes it, it
carries the run as far as it can go without them, stops at the first human gate or failure,
states exactly what they must do next, and exits. Invoked again after they act, it reads the
artifacts and picks up from wherever the run stands.

**This is a conductor, not a fifth brain.** Every analytical, planning, implementation, and
reporting judgment already has a home in one of the four stages. The design constraint is
thinness: any capability that tempts this skill to redo, patch, or second-guess stage work is a
defect rather than a feature.

**What it is worth.** The knowledge that stage two reads stage one's index, that stage three's
pre-flight is the real gate, that stage four holds its close-out sitting in the middle of its
own procedure, and which lint phase applies at which moment — all of that used to live in the
owner's head. It lives in `scripts/pipeline_state.py` now. The skill succeeds when the owner
stops thinking about the pipeline's internals and thinks only in terms of the next brief.

## Absolute rules

These bind regardless of circumstances, deadlines, or apparent convenience. They are
prohibitions rather than capabilities, in the tradition of the executor's charter, and the shape
is deliberate.

1. **Never edit a stage artifact.** Not a status, not an `approved` field, not a decision, not
   one character. The write surface is the conversation with the owner and nothing else. This is
   checkable rather than only asserted: take a checksum set before invoking a stage and after,
   and every difference must be attributable to that stage.

2. **Never answer an owner decision, however obvious.** Not an escalation, not a ratification,
   not a defect, not plan approval. A gate brief may restate a stage's recorded recommendation
   and must label it as that stage's; it may never add one of its own. Presentation counts as
   recommending — ordering, emphasis and length are all ways of pushing an answer without a
   recommending sentence.

3. **Never bypass, weaken, or reorder a gate, a lint, a validation, or a pre-flight**, under any
   instruction short of the owner amending the requirements themselves. "Just this once" is not
   an input this skill accepts. Stage targeting chooses where to stop, never what to skip.

4. **Never invoke a stage whose preconditions fail**, and never merge, push to a protected
   branch, or deploy.

5. **Never soften a stage's diagnosis.** Relay it verbatim, with its location. Never retry a
   stage on your own initiative and never patch around one. Every diagnosis in this suite was
   written to be acted on, and a summary of it is strictly less useful than the thing itself.

6. **Never add a validator.** Every verdict comes from one of the four stages' own tooling. A
   second opinion about whether an artifact is valid is a second opinion that drifts — and at
   one transition it would be worse than that: pre-flight's rewrite check has nothing else
   standing behind it, so a second implementation would be a *competing* opinion rather than a
   redundant one, with nothing positioned to notice them diverge.

## Inputs

| Option | Meaning | Default |
|---|---|---|
| `--repo <path>` | The repository | `.` |
| `--assessment <path>` | The assessment report | `docs/test-assessment.md` |
| `--plan <path>` | The plan | `docs/test-plan.md` |
| `--ledger <path>` | The run ledger | `docs/test-ledger.json` |
| `--sheet <path>` | The close-out decision sheet | `docs/test-closeout.md` |
| `--report <path>` | The narrative report | `docs/test-report.md` |

If the user gave hints in prose rather than flags, use them the same way.

## Procedure

The whole procedure is a loop: derive, decide, invoke, compare, repeat. It ends when the state
is a gate, a failure, or a closed run.

### Step 1 — Check the install

```bash
python3 <skill>/scripts/siblings.py
```

One line per module this skill reaches for across the other four. **A missing sibling is not a
degraded capability here but an absent one** — this skill has no analytical tooling of its own,
so there is nothing to fall back on. Relay the stop and end the run.

### Step 2 — Derive the state

```bash
python3 <skill>/scripts/pipeline_state.py --repo .
```

It prints the position, the blocking condition, the next action, the stage to invoke, any
diagnosis to relay verbatim, the repository drift flag, and the open-run flag.

Read `references/state-model.md` before acting on an unfamiliar position. It gives every
position normatively: how it is detected, what its next action is, and what its brief must
contain.

**Do not derive the state yourself, and do not second-guess what it derived.** If the position
looks wrong, that is a defect in the script and worth reporting; it is not an invitation to
form your own view by reading the plan.

### Step 3 — Report the two signals, whatever the position

Both can be true at several positions and both belong in whatever you write next.

**The drift flag** names the commits that disagree and the stage whose own revalidation decides
what the disagreement costs. State both. **Never say a drift is harmless** — that is an opinion
about code this skill has not read.

**The open-run flag** says whether a run is already open. Starting a new run while one is open
needs the owner's explicit instruction, and the brief states what the open run will orphan
before that instruction is accepted.

### Step 4 — Act on the position

**If the position is a gate** (`awaiting-approval` or `awaiting-closeout`), write the brief and
stop. Read `references/gate-briefs.md` first. Extract the facts with:

```bash
python3 <skill>/scripts/gate_brief.py docs/test-plan.md --gate 1 --repo .
python3 <skill>/scripts/gate_brief.py docs/test-plan.md --gate 2 --repo .
```

**If the position carries a diagnosis to relay**, relay it verbatim and stop. Read
`references/failure-handling.md`.

**If the position names a stage to invoke**, take the checksums, invoke it, and take them again:

```bash
python3 <skill>/scripts/pipeline_state.py --repo . --checksums
```

Invoke the stage as a **subagent with `subagent_type: "general-purpose"`**, using the verbatim
briefing from `references/stage-invocation.md`. Pass the skill name, the artifact paths, and the
repository — **locations, never content, and never your own conversation.**

**If the position is `closed`**, write the closing brief: the branch is settled, what each
decision did to it, what the ledger now holds open, and the merge instruction. **Do not merge.**

### Step 5 — Compare the checksums, then go back to Step 2

Every artifact that changed must be attributable to the stage just invoked. An artifact that
changed and should not have means something wrote outside its stage, and the run's record is no
longer trustworthy — stop and say so rather than continuing.

Then derive again. The new state is what the invoked stage left behind, read from the artifacts
rather than from what the stage said about itself.

**Keep going until the state is a gate, a failure, or a closed run.** That is the ratchet: one
invocation advances through as many transitions as preconditions permit. A single invocation can
run assessment and planning and stop at gate one; another can execute and stop at gate two;
another can close the run.

## The two gates, and why they sit where they do

**Gate one is between stages two and three.** The orchestrator invokes stage two, stops, and
invokes stage three in a later invocation. Plan approval is the owner's act and nothing derives
it, so **every fresh run reaches gate one and halts**.

**Gate two is inside stage four**, which is the structurally awkward one and the reason stage
four is invoked in two segments. Stage four holds the gate at its Step 2 and assembles the
report at its Step 4, after the answers have been applied — because the report reports what the
close-out decisions did to the branch, so it cannot precede them.

**An empty gate does not stop the ratchet and is still applied.** A run that registered no
defects gets a sheet whose body is a `No defects` section, and the run closes by running
`--apply` over it, which is what writes the records the closed phase requires. Passing through
gate two without stopping is correct; skipping it is not.

## Degradations to record

Every one of these that applies goes in the brief, with what it costs — not omitted and not
softened:

- The assessment's verification pass recorded as `skipped`, so every finding in it is
  single-sourced
- Any degradation the assessment declared, carried forward with the cost the plan recorded
- Repository drift, with both commits and the stage that decides what it costs
- An open run, and what starting a new one would orphan
- A partial execution run, and which part is missing
- Any R-4.2 consistency check that failed at the executed position, and what it means the
  report cannot vouch for
- A plan whose scope figures show it reaching a small share of what is reachable

## What this stage never does

- **Perform any stage's work.** Not assessment, not planning, not writing a test, not writing a
  report, not one line of any of them.
- **Edit any stage artifact**, including to make a check pass. A check that passes because
  something was edited to make it pass reports the same green as one that passed honestly.
- **Answer a decision reserved to the owner**, including the one at `execution-incomplete` where
  the state is perfectly visible and one of the two ways forward destroys work.
- **Retry a stage, or patch around a failure.** If a stage failed for a reason a retry would fix,
  that is a defect in the stage, and hiding it behind a retry means it is never found.
- **Write anything durable.** No state file, no manifest, no orchestration log. Orchestration
  history is recoverable from what the stages already record — commits and the ledger's run
  entries — and a separate log would be one more paired record to drift.
- **Merge, push to a protected branch, or deploy.**

## Repeatability

Two invocations against an unchanged repository produce the same diagnosis and propose the same
next action. This is a tested property rather than an aspiration:

```bash
python3 <skill>/scripts/pipeline_state.py --selftest
```

It drives every position in the state model from the fixtures in
`~/Projects/code-coverager/fixtures/`, asserts the diagnosis and the next action for each, and
asserts that a second derivation against the same inputs is byte-identical to the first.

The `closed` position has no fixture set and is validated against a real closed run, because
reaching it needs a report that passes `trace_report.py` — which regenerates the report from the
run record and demands every generated byte match. A hand-written fixture report would be a
report nothing generated, wearing the authority of one that was.

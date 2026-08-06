---
name: test-reporting
description: Close a test-execution run — assemble the narrative report from the run record, hold the close-out gate where the owner decides every defect and the consequences are applied and committed, and append the durable cross-run ledger. Use when asked to report on a test run, close out a run, decide what to do about discovered defects, or act on an executed docs/test-plan.md. It is the only stage that closes a run.
---

# Test Run Reporting and Close-out

Stage four of a four-stage test improvement workflow. This stage closes a run. It does not
assess, plan, or write tests.

Its input is an executed plan on a work branch. Its output is a report anyone can read, a
branch where every defect carries the owner's decision with the consequence applied and
committed, and a run ledger the next run is bound to answer for.

**A run is not closed until the gate is complete.** Stage three ends by telling the user what
it found; it is forbidden from answering any of it. Everything it surfaced arrives here as
decision debt, and this stage exists to discharge it. The owner merges the work branch after
close-out — this stage never merges.

**The report's purpose constrains what it may say.** This pipeline exists to earn the sentence
"you can run this suite and trust it." That sentence is not true as a scalar, and asserting it
as one would be the report-level version of the vanity coverage number the whole project exists
to kill. What a run produces is a set of bounded, evidenced statements, and the report states
each at exactly its strength: no more, and — this half is easier to forget — no less.

**An honest report of a bad run is the success condition. A flattering report of any run is the
failure condition.**

## Absolute rules

These bind regardless of circumstances, deadlines, or apparent convenience.

1. **Never state a figure you did not compute.** Every number in the report comes from the run
   record, and `trace_report.py` proves it. A figure absent from the record is reported absent
   and raised as a pipeline finding — never reconstructed, never estimated, never inferred from
   what the number "must have been". A reconstructed figure is indistinguishable in the report
   from a measured one, and the report's whole epistemology rests on that difference staying
   visible.

2. **Never reduce the run to a grade.** No score, no letter, no percentage of overall health,
   no "production-ready", no "fully covered". The trust statement is a bounded map with marked
   terrain and marked voids, and a grade is precisely the compression that hides the voids.

3. **Never answer a defect on the owner's behalf.** All four options are theirs. One of them —
   downgrading a defect so the suite reports green over a real failure — is available to nobody
   else at any point in this pipeline. If the sheet comes back unanswered, the run stays open;
   that is the correct outcome, not a problem to route around.

4. **Never edit outside a decision's named test.** The close-out executor inherits stage three's
   charter in full. Fixing a defect is the owner's work outside this charter — `fix-the-code` is
   an answer that applies nothing. An edit outside the surface aborts the whole close-out.

5. **Never merge, push to a protected branch, or deploy.** The branch is presented for merge and
   the owner merges it.

6. **Never edit the ledger by hand.** Every append and every state change goes through
   `ledger.py`. The ledger is what binds the next run, and a hand-merged one is the only
   artifact in this suite whose corruption produces no error anywhere.

## Inputs

| Option | Meaning | Default |
|---|---|---|
| `--plan <path>` | The executed plan | `docs/test-plan.md` |
| `--assessment <path>` | The assessment, for the full lint | `docs/test-assessment.md` |
| `--repo <path>` | The repository root | `.` |
| `--ledger <path>` | The run ledger | `docs/test-ledger.json` |

If the user gave hints in prose rather than flags, use them the same way.

## Procedure

### Step 1 — Check the install and read the run

```bash
python3 <skill>/scripts/siblings.py
python3 <skill>/scripts/run_record.py docs/test-plan.md --repo . --no-suite
```

The first prints one line per module this stage imports from its three siblings. The second
performs R-4.2's cross-checks and prints them: statuses agree, every registry entry has a
committed test, every commit on the branch is named by an item or a decision, every declared
coverage delta was measured, every completed item has a footprint diff.

**Read the failures rather than repairing them.** Each one is a pipeline finding about stage
three and each degrades the report's stated confidence. Editing the run summary to make a check
pass destroys the only evidence that the pipeline has a gap.

### Step 2 — Hold the close-out gate

```bash
python3 <skill>/scripts/closeout.py docs/test-plan.md --repo . --brief
```

This writes `docs/test-closeout.md`: one section per defect carrying the claim, its source and
authority, what the code actually does, the red test, the fresh-context verification that let
it stand, and the four options with what each costs. Then it stops.

**Give the sheet to the owner and wait.** Read `references/closeout-brief.md` before presenting
it, so you can answer questions about the options without improvising. Do not fill any answer
in, do not recommend one so strongly that the sheet is a formality, and do not proceed on an
inferred answer. A gate the owner did not actually attend is decision debt wearing a record.

When the sheet comes back:

```bash
python3 <skill>/scripts/closeout.py docs/test-plan.md --repo . --apply --dry-run
python3 <skill>/scripts/closeout.py docs/test-plan.md --repo . --apply
```

`--apply` validates every answer, performs each transformation, verifies it through the check
runner, makes one commit per consequence, measures that commit's footprint against R-6.3's edit
surface, and writes the records into the plan.

**One of the four needs you.** `requirement-wrong` means rewriting the failing test to assert
what the code actually does, and that is the single judgment this stage retains — exactly
parallel to stage three retaining only "how to express a claim as a test". A script that
generated the assertion would produce a test asserting whatever the code currently returns,
which is a characterization pin wearing a specification's label. `--apply` stops and tells you
which test to rewrite; write it against the registry entry's `observed` field, keep the
`# claim:` annotation, touch nothing else, and run `--apply` again.

The gate is one sitting. A partially answered sheet is refused rather than half-applied.

### Step 3 — Assemble the record, the findings, and the record again

```bash
python3 <skill>/scripts/run_record.py docs/test-plan.md --repo . --phase closed --write
python3 <skill>/scripts/findings.py    docs/test-plan.md --repo . --phase closed --write
python3 <skill>/scripts/run_record.py docs/test-plan.md --repo . --phase closed --write
```

Twice, and the repetition is not an oversight. The findings are derived from the record, and
the linter recomputes the record's finding list against the blocks — so the record has to be
written before the findings exist and again after they do.

Read `references/pipeline-findings.md`. The derivation is deterministic and its *reading* is
yours: a recurring finding is worth more attention than a new one, and a finding that has
recurred three times without being retired is a requirements amendment waiting to be written.

### Step 4 — Assemble the report and write the prose

```bash
python3 <skill>/scripts/assemble.py docs/test-plan.md --repo .
```

This writes `docs/test-report.md` with R-5.2's fixed section order, every table filled from the
record, and nine marked prose slots. Fill each slot between its markers.

**You never type a number.** Everything countable is already in a table above the paragraph
that discusses it. Your job is to say what the tables mean — which is the job a table cannot do
and the reason the slots exist at all.

Three slots have their own reference and you should read it before writing them:

- the executive layer — `references/plain-language-brief.md`
- the trust statement — `references/trust-statement.md`
- the pipeline findings — `references/pipeline-findings.md`

Then:

```bash
python3 <skill>/scripts/trace_report.py docs/test-report.md --repo .
```

It regenerates the report from the record and proves every generated region is byte-identical,
then checks every number you wrote against the record's figure set. **Never make this pass by
adding a figure to the record.** The record is derived; a number you put there by hand is a
number nobody computed wearing the record's authority.

### Step 5 — The one verification pass

Run the fresh-context reader described in `references/plain-language-brief.md` against the
executive layer alone.

**Stage two runs no verification agent and gives the reason: the linter checks form and the
owner checks substance, so an agent between them re-checks what the owner is about to check.**
That reasoning holds here for everything except R-5.3's plain-language requirement, which is
the one property an author cannot check about their own writing. You know what every term
means, so you cannot tell which of them you failed to define. The reader has no pipeline
context, gets the executive layer and nothing else, and is asked which terms they could not
define and which sentences they could not act on. Anything they name reopens the layer.

### Step 6 — Append the ledger and close

```bash
python3 <skill>/scripts/ledger.py docs/test-ledger.json --init --repository <name>   # first run only
python3 <skill>/scripts/ledger.py docs/test-ledger.json \
        --append docs/test-execution-log/run-record.json --plan docs/test-plan.md
python3 <skill>/scripts/ledger.py docs/test-ledger.json --open
python3 <skill>/../test-planning/scripts/plan_lint.py docs/test-plan.md \
        --assessment docs/test-assessment.md --phase closed
```

The append reports closure *candidates* — open defects from earlier runs whose tests did not
fail this time — and closes none of them. Read `references/reconciliation.md` for why: "did not
fail" and "passed" are not the same fact, and a run whose plan does not touch that area may
never have executed the test at all. Close one explicitly, with the fixing commit and how you
established it, or leave it open.

Then commit the report, the plan, and the ledger, and tell the user: the branch, what each
decision did to it, what is still open, and what the next assessment is now obliged to
reconcile. **Do not merge.**

## Degradations to record

Every one of these that applies is stated in the report with its cost to the report's
confidence (R-9.3), not omitted and not softened:

- Any R-4.2 consistency check that failed, and what it means the report cannot vouch for
- A run summary read from the sidecar rather than from the plan, which the linter never checked
- The suite unmeasured at close-out, and why
- Any coverage delta with no `after` figure, distinguishing an item that never ran from a
  measurement that failed
- Any close-out check reported `not-run`
- The plain-language reader not run, or run and its findings not acted on
- Open ledger items carried forward without being re-examined this run

## What this stage never does

- **Re-derive a figure stage three should have produced.** That is a pipeline finding, and
  reconstructing it hides the finding and produces a number with no basis.
- **Repair the run summary or the plan writeback.** Both are stage three's record of what
  happened. An inconsistency is reported, never edited away.
- **Fix a defect.** `fix-the-code` applies nothing on purpose; the red test is the ready-made
  verification for whoever does the fix.
- **Retire a pipeline finding because it stopped appearing.** R-7.5 and R-8.2: retirement is
  explicit and names the change that addressed it. A finding that goes quiet because nobody
  looked is still open.
- **Merge, push to a protected branch, or deploy.**

## Repeatability

A second close-out of the same run with the same answers must produce the same report, the same
commits' worth of change, and the same ledger entry — the commit hashes excepted. Everything
deterministic is deterministic by construction: the record is copied forward, the findings are
derived under a closed taxonomy in a fixed order, the report is assembled by a script, and the
ledger append is a merge with no ordering freedom.

The judgment parts are the prose and the `requirement-wrong` rewrite. Anchor the first to the
tables above it and the second to the registry entry's `observed` field, and both come out the
same way twice.

`~/Projects/coverager-fixture` exists to test exactly this, and its README says how to reset
it. Closing it out four times from the same starting point, once per option, is what proves all
four transformations and that the two no-op options really commit nothing.

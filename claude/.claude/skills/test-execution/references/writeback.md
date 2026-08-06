# Writeback

What this stage writes, where, and — the part that is not obvious — **when**.

The normative schema lives in the planning skill, at
`references/schema/execution-writeback.md`. This document is the procedure.

## The shape of it

| What | Where | Written |
|---|---|---|
| `status` | On the work item, rewritten in place | At the start and end of every item |
| `commit` | On the work item | On completion |
| `actuals` | On the work item | On completion, and on a failure worth recording |
| `diagnosis` | On the work item | On `failed`, `stale`, `blocked-by-failure` |
| `label`, `evidence` | On a claim | Only for a dispute |
| `execution-log` blocks | A new section at the end of the plan | One per attempt |
| `defect` blocks | A new section at the end of the plan | One per registry entry |
| `run-summary` block | A new section at the end of the plan | Once, at run end |
| Full failure output, preserved diffs, evidence | `docs/test-execution-log/`, referenced by path | As produced |

**Statuses and short fields are rewritten in place; bulk goes to the sidecar.** The plan stays
something a person can read, and the evidence stays complete.

## Why the plan file at all

Stage two established the plan as the running record the stage four report is built from. A
separate results file would have been easier to write and would mean two documents that can
disagree about what happened — and the one a person opens is the plan.

So `planio.py` rewrites spans rather than re-serialising the document. **The plan you are
writing into is the plan the owner reviewed, with their comments in it.** A round trip through
any YAML emitter would return a technically equivalent file with every comment gone and every
folded scalar refolded, and the owner would have no way to see what execution actually changed.

## Every write is re-linted, and rolled back if it fails

R-4.2 makes stage two's linter this stage's entry gate, so a write that linter rejects is a
write that must never land. `planio.Plan` lints after every write and restores the previous
bytes on failure, reporting what the plan would have said.

The check is relative to a baseline captured when the plan is loaded, so a plan that already
had a problem can still be written to and only problems a write *introduces* roll it back. In
practice the baseline is empty, because pre-flight refuses to start a run on a plan that does
not lint.

## The order, which is load-bearing

Because every intermediate state must lint clean, the executed-phase rules dictate a sequence.
This is not a style preference; a write in the wrong order is rejected and rolled back, which
is a correct outcome and a confusing one to debug at three in the morning.

### A completed item

```
1.  status: in-progress
2.  (the work)
3.  append the execution-log block for this attempt
4.  actuals, then commit
5.  status: done            (or done-with-defect)
6.  only now, append any defect block
```

Step 6 sits last because a `defect` block requires its item to be `done-with-defect`
(`defect-item-not-done-with-defect`). Steps 3 and 4 sit before 5 because a completed item must
carry a log entry, a commit, and actuals — `missing-execution-log`, `done-without-commit`,
`done-without-actuals`.

### A dispute

```
1.  diagnosis
2.  status: failed
3.  the claim's evidence
4.  only now, the claim's label: disputed
```

Step 4 sits last because a `disputed` claim requires both an evidence pointer
(`disputed-without-evidence`) and a failed item asserting it (`dispute-item-not-failed`).

### A failure

```
1.  append the execution-log block for the final attempt, with preserved-diff
2.  diagnosis
3.  status: failed
```

## Idempotence

Every write is idempotent: setting a field to the value it already holds changes nothing, and
upserting a block whose natural key already matches replaces it rather than stacking a second
copy beside it. That is a requirement rather than an optimisation — a run that resumes, or an
executor that writes the same status twice, must not churn the file or duplicate a record.

The natural keys: `{item, attempt}` for a log entry, `{id}` for a defect, `{}` for the single
run summary.

## What you never write

`R-2.1` lists the fields this stage may write, and everything else in the plan is planner
content. In particular:

- **Never `files-touched`.** If the actuals exceed it, the item fails (R-2.2). Widening it to
  match would destroy the one measurement that could ever justify running slices concurrently,
  which is the whole point of recording actuals separately.
- **Never a completion check.** If a check is wrong, the item fails and the diagnosis says so.
  A check you edited is a check nobody ran.
- **Never a claim's `text`**, and never a claim's label except `disputed`. Relabelling a claim
  you wrote the test for is marking your own homework, and `ratified-as-observed` is the
  owner's close-out act.
- **Never a defect's `resolution`.** That is the owner's answer at stage four, and one of the
  answers available to them — downgrading the defect — is not available to you at all (R-2.5).
- **Never `plan-meta.approved`.** The owner approved the plan or they did not.

## The sidecar

`docs/test-execution-log/` holds what is too bulky for the plan:

| File | Holds |
|---|---|
| `preflight.json` | The pre-flight record: approval, drift, inherited failures, the branch, the narrowings it already found |
| `coverage-baseline.json` | Slice zero's recorded figures, which every `coverage-delta` is measured against |
| `run-summary.json` | A JSON copy of the run summary, for stage four |
| `<item>-attempt-<n>.txt` | Full command output for one attempt |
| `mutation-<claim>-<file>.txt` | The whole mutation transcript: before, mutated, restore, after |
| `standing-invariant.txt` | The most recent whole-suite run |
| `.mutation-in-progress.json` | Present only while a mutation is applied. Its presence at startup means a previous run died mid-mutation, and the check runner restores from it before doing anything else |

The plan references these by path. Commit them alongside the plan, in the record commits rather
than in an item's own commit.

## Commits

**Two kinds, and keeping them apart is what makes the footprint measurable.**

An **item commit** carries the item's work and nothing else. Stage by path, from the declared
footprint, never with `-A`:

```bash
git add tests/test_money_parse.py
git commit -m "WI-06: unit tests for parse_amount across separator styles"
```

Staging by path is what makes R-2.2 enforceable rather than aspirational: a file outside the
footprint cannot get into the commit by accident, and `actuals.py` reads the footprint from
that commit's own diff.

A **record commit** carries the plan file and the sidecar:

```bash
git add docs/test-plan.md docs/test-execution-log
git commit -m "record: WI-06"
```

R-5.3 already implies the split — it writes the final status *after* the commit, so the
writeback was never going to be inside it. One work commit per completed item, attributable by
identifier, is what the requirement asks for and what this preserves.

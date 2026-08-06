# The run ledger: normative field reference (R-7.1)

`docs/test-ledger.json`, committed in the repository beside the other pipeline artifacts,
appended by every run through `scripts/ledger.py` and by nothing else.

## The name

This project uses the word "ledger" for three unrelated things and the qualification is never
dropped:

- **the run ledger** — this file, and always called that in prose;
- **the derivation ledger** — the file-and-symbol accountability list `partition.py` emits in
  the planning skill;
- **`ledger`** — the imaginary repository the linter fixtures describe, which does not exist on
  disk and must never start to.

## Why one file

Section 11 of the requirements leaves the format open between a single file and a directory of
per-run entries. It is a single file.

Reconciliation's central query is *what is open right now*, which a single file answers by
reading it and a directory answers only by folding every entry in order — and a fold whose
order is wrong produces a plausible answer rather than an error. The single file also gives a
readable `git diff` per run, which is what makes the ledger auditable by a person rather than
only by a script.

The cost is merge conflicts if two runs ever proceed in parallel. The pipeline is serial by
construction: one work branch, merged by the owner before the next run starts.

## Top level

```json
{
  "ledger_version": "1.0",
  "repository": "coverager-fixture",
  "runs": [], "claims": [], "defects": [], "disputes": [],
  "amendment_flags": [], "findings": [], "scope": [],
  "decisions": [], "footprint_accuracy": []
}
```

`ledger_version` is handled the way the assessment index handles its version: an older ledger
is routed to a narrow migration rather than refused. There has been no earlier version, so
there is no migration to write yet.

## `runs`

One entry per closed run, in order. This is the array R-7.4 means by "the report of an
incremental run states its baseline run explicitly": the previous entry is that baseline.

| Field | Meaning |
|---|---|
| `run_id` | The close date and the short closing commit, as `2026-08-04-a1b2c3d`. The date is what a person searches for; the commit is what makes two close-outs on one day distinguishable, which the fixture repository produces routinely. |
| `closed` | Date the gate completed |
| `branch`, `base_commit`, `close_commit` | Where the run happened and where it ended |
| `report` | The path the narrative report was written to. The report is overwritten by the next run; this plus `close_commit` is how an old one is retrieved from history. |
| `baseline_run` | The `run_id` this run was a diff against, or null |
| `commit_distance` | Commits since the previous close-out — R-5.6's decay proxy |
| `headline` | Items by status, claims by authority, defect and dispute counts, coverage targets met against declared, narrowing count. Every figure copied from the run record, none recomputed. |

## `defects`

| Field | Meaning |
|---|---|
| `id` | `DF-n`, from the plan's registry |
| `claim` | The claim it contradicts |
| `summary` | The registry entry's `observed` text |
| `test` | `{file, name}` — the red test |
| `state` | `open`, `fixed`, `downgraded`, `requirement-amended`, `contested` |
| `raised_in`, `last_seen` | Run identifiers |
| `decision` | `{option, run, commit}` — the close-out answer |
| `fixed_in`, `fixing_commit`, `fix_evidence` | Set only by `--close-defect` |

**`fix-the-code` and `accept-with-red` both leave the state `open`.** The difference between
them is who enforces the red, not whether the defect is still real, and two states nobody could
act on differently would be two states nobody could act on differently.

## `disputes`

Keyed by `claim` rather than by an identifier of its own, because a dispute *is* a claim in a
particular state. `state` is `open`, `corrected`, or `contested`; `corrected_text` holds what
the owner said the claim should have been, for the next round of planning to start from.

## `amendment_flags`

`DA-n`, one per `requirement-wrong` decision. `document`, `passage`, `state` of `open`,
`amended`, or `contested`. A defect in a document, tracked like any other finding until
somebody amends the document or contests the flag.

## `findings`

`PF-nn`, with `category`, `summary`, `evidence`, `state`, `first_seen`, `last_seen`,
`occurrences`, `retired_by`, and **`signature`**.

The signature is what makes recurrence detectable across runs: the category plus the
identifiers the finding is about. See `pipeline-findings.md`.

`state` moves `open` → `recurring` on the second occurrence, and to `retired` or `contested`
only through an explicit call. A finding re-raised while retired is reopened as `recurring`
with its `retired_by` cleared, which is the ledger noticing that the retirement did not work.

## `scope`

R-6.6: close-out may complete with a partial run, and the undelivered scope is carried here as
open items rather than blocking closure. One entry per work item that ended `failed`, `stale`,
`skipped`, `blocked-by-failure`, `in-progress`, or `pending`, keyed by the item identifier.

An entry moves to `delivered` when a later run completes that item.

## `claims` and `decisions`

`claims` is every claim with its current authority and the runs it was seen in — what R-7.3
holds the planner to when it must not re-derive a claim already asserted at a given authority.

`decisions` is the log: every close-out record, flattened, with its run.

## `footprint_accuracy`

One row per run: items measured, how many came out exact, how many over-declared, how many
touched something undeclared. Planning R-10.3 gates concurrent execution on this history, and
one run is not history — this is where it accumulates.

## What is open

`ledger.py --open` folds five arrays into one list in a fixed order: defects, disputes,
amendment flags, pipeline findings, undelivered scope. An item is open when its state is `open`
— or, for findings, `open` or `recurring`.

That list is consumed by three things: `reconcile.py`, which binds the next assessment;
`plan_lint.py --ledger`, which binds the next plan; and the report's carried-forward table. All
three read the same function, so none of them can develop its own opinion about what "open"
means.

## Closing is always explicit

R-8.2 says a pipeline finding is retired only explicitly. The same discipline is applied to
defects, disputes, and amendment flags for a reason the retirement rule does not state: the
alternative is inference, and inference here means concluding that a defect is fixed because
its test did not fail in a run that may not have run it.

So `--append` reports **closure candidates** and closes nothing:

```
1 closure candidate(s) — reported, not applied:
  DF-1 (test_parse_amount_reads_the_german_separator)
    the final suite was measured and this test was not among the expected failures. That is
    consistent with the defect being fixed and also with the test not having been run.
    close it with: --close-defect DF-1 --commit <sha> --evidence <how you established it>
```

Every state change has its own flag and every one demands evidence: `--close-defect` needs the
fixing commit and how it was established, `--retire-finding` needs the change that retired it,
`--contest` needs a note. All three are dispositions rather than dismissals — the evidence is
what a later reader gets instead of the item.

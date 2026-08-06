# The Execution Loop

The per-item lifecycle and the slice boundary. R-5.1 to R-5.4 and R-6.1 to R-6.4.

## Order

Slices execute in plan order. Within a slice, items execute in dependency order, ties broken
by identifier. Neither is a judgment you make:

```bash
python3 <skill>/scripts/planio.py docs/test-plan.md --show
```

gives the whole order, computed once. Two runs of the same plan cannot disagree about what
comes next, which is what makes a repeated run repeatable.

Execution is **sequential**. Concurrency is deferred until the footprint measurement this run
produces says it would be safe.

## The item lifecycle

The order below is not stylistic. Stage three re-lints the plan after every write and rolls
back anything that fails, so each intermediate state has to lint clean — and the executed-phase
rules force this sequence. `references/writeback.md` states why each step sits where it does.

### 1. Write `in-progress`

```bash
python3 <skill>/scripts/planio.py docs/test-plan.md --set WI-04 status in-progress
```

### 2. Implement

This is the one judgment you retain. What it means depends on the item's type:

| Type | What implementing it means |
|---|---|
| `infrastructure` | Make the configuration change the item names. Nothing else. |
| `characterization` | Pin current behavior **without asserting it is correct**, which is what makes it safe to write before anybody has agreed what correct means |
| `seam` | Make the named change to production structure, and nothing else. Behavior must not move; the guard is what proves it |
| `unit-tests` | Write tests asserting the item's claims. `references/test-authoring.md` |
| `test-repair` | Change existing tests so they can fail. The mutation checks are the only evidence this happened |

**Stay inside the declared footprint.** Not approximately — exactly. A file you touch that the
footprint does not name fails the item under R-2.2, and the fix is to fail and say what was
needed, never to widen the footprint.

**Annotate every test with the claims it asserts**, as `# claim: C12`. The convention is in
`references/test-authoring.md` and the checker reads it.

### 3. Run the check runner

```bash
python3 <skill>/scripts/check_runner.py docs/test-plan.md --item WI-04 --repo . --json > checks.json
```

**You never grade your own checks.** That is the entire reason this is a script: an agent
deciding whether its own work passed decides generously, not from bad faith but because it
knows what it meant.

Mutation checks need the edit applied, and applying it is reading prose, which is model work.
Prepare the mutated file **outside the repository** and hand it in:

```bash
cp tally/money.py "$SCRATCH/money.mutated.py"
# make the named edit in $SCRATCH/money.mutated.py, and only that edit
python3 <skill>/scripts/check_runner.py docs/test-plan.md --item WI-04 \
        --mutation-check C1 --mutated-file "$SCRATCH/money.mutated.py" --repo . --json
```

Everything from there is one process. `references/check-runner.md` gives the protocol in full
and says why it must not be delegated.

### 4. Append the attempt to the execution log

Every attempt, including the one that worked first time. The `summary` says what was attempted
and what the runner reported; where the two differ, say which is which.

### 5. Record actuals and the commit

Commit the item's work first, staging **by path** from the declared footprint rather than with
`-A`. Staging by path is not tidiness: it is what makes the footprint rule enforceable rather
than aspirational, because a file outside the footprint cannot get into the commit by accident.

```bash
git add tests/test_money_parse.py
git commit -m "WI-04: unit tests for parse_amount across separator styles"
python3 <skill>/scripts/actuals.py docs/test-plan.md --item WI-04 --commit HEAD \
        --checks checks.json --attempts 1 --repo . --json
```

`actuals.py` reads the files touched from the commit's own diff, never from what you remember
doing. If it reports the footprint `exceeded`, the item fails — see step 7.

**The plan file and the sidecar log are not part of an item's commit.** They are the run's
record, not the item's work, and they are committed separately so that the item's diff is
exactly what the item did. R-5.3 already implies this: it writes the final status *after* the
commit.

### 6. Write the terminal status

`done`, or one of the outcomes below.

### 7. When it does not work

| Situation | Do |
|---|---|
| A check failed and you can fix it | Retry, within the budget. Fixing means making the work right, never making the check easier |
| The retry budget is exhausted | `failed`, with a diagnosis: what was attempted, what the runner reported, and your best explanation — **marked as your explanation rather than as a finding** |
| You broke something else (new red outside the registry and the inherited list) | Repair it within the budget, or revert it fully before failing. **No item ends with the working tree dirtier than it found it** |
| A seam's guard failed after the refactoring | Revert immediately, preserve the diff on a side branch named in the diagnosis, fail the item. A behavior-changing refactoring is never committed and this is not a candidate for retry-until-green |
| A test of a cited or ratified claim failed | Not a failure. `references/defects-and-disputes.md` |
| A test of a pinned claim failed | Not your failure either. Same reference, opposite handling |
| The item needs work the plan did not describe | `failed`, saying exactly what was missing. Do not do the extra work |
| A dependency failed, went stale, or was skipped | `blocked-by-failure`, transitively, with a diagnosis naming the dependency |

**Fail forward.** A failed item marks its dependents `blocked-by-failure` and execution
continues with independent items and slices. Report at the end; never hang mid-run.

### What a failed item leaves behind

Nothing committed, and the diff preserved on a side branch named in the execution log's
`preserved-diff`. The reasoning is that the item is the unit: an item whose purpose was
assertion strength and whose mutation check kept passing has not been done, even if four of
its five tests improved, and committing the four would leave the plan saying an item completed
when its own evidence says otherwise. The preserved branch means the work is not lost — it is
evidence for the report and a starting point for the re-plan.

## The slice boundary

**Each slice executes in a fresh context whose sole briefing is the plan file and the
repository** (R-5.2). Not a summary of the last slice, not what you remember about the
codebase. Two things follow:

- Context growth is bounded, so a twenty-item plan does not degrade by its last slice.
- **The plan's self-sufficiency becomes a tested property on every run**, not just at review.
  A slice that cannot proceed without information the plan lacks fails with that stated, and
  that is a planning defect worth hearing about rather than a gap to fill from memory.

Before declaring a slice done, run the judgment verifier of `references/slice-verification-brief.md`.
A rejection reopens the item against its retry budget; a slice with weak assertions fails as a
slice rather than surviving to the final report.

## The standing invariant

After every completed item, the full suite is green **except** tests named in the defect
registry and the failures pre-flight recorded. The check runner measures it on every item
without being asked.

Anything else red is breakage you caused. Repair it within the retry budget or revert it fully
and fail the item. The reason the invariant is measured against pre-flight's recording rather
than against absolute green is that you are responsible for causing no new red, not for
repairing red you inherited — and repairing inherited red would be outside every item's
footprint anyway.

## The retry budget

Three attempts by default. What a retry is for depends on what failed:

- **An ordinary check failure**: fix the work.
- **A failing test of a cited or ratified claim**: R-7.2 narrows the budget to one question
  only — *is the test faithful to the claim?* Not "is the code right", which is not yours to
  decide. Once you are satisfied the test is faithful, stop retrying and register the defect.
- **A mutation check that keeps passing**: the retry is for strengthening the assertion. If
  the claim describes something the code discards before any test can see it, no assertion
  will do, and the honest outcome is `failed` with that stated. It is a planning defect and
  saying so is more useful than three more attempts.

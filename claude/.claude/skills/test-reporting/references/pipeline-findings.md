# Pipeline findings: the taxonomy, with a recognition test per category (R-8.1)

A pipeline finding is evidence a run produces **about the pipeline itself** rather than about
the repository it ran against. The plan asked for something that could not be done; the
assessment had gone stale; the planner's reading of the code was wrong; declared footprints did
not match real ones; a script or a schema fell short in use.

They are recorded with the same identifier discipline as repository findings, they live in the
run ledger, and they are retired only explicitly. They are the raw material for requirements
amendments — this project has already run that workflow by hand three times, and these are what
it would have consumed.

## The dividing line

Ask: **if this repository were replaced with a different one, would the problem still be
there?**

A test that fails because the code is wrong is a repository finding — a defect. A test that
could not be written because the plan did not say which of two behaviors to assert is a
pipeline finding: the same gap would appear in any repository planned that way.

The line is not always sharp and the categories below are how it is drawn in practice.

## The five categories

The set is closed. A finding that fits none of them is a repository finding wearing the wrong
label, or it is a sign the taxonomy needs a sixth category — which is an amendment to the
requirements document, not a judgment call inside one run.

### 1. `planning-gap`

**Recognition test.** An item did not deliver, and the reason is something the plan should have
settled and did not.

Three shapes, and `findings.py` raises them separately because they cost different things:

- An item ended `failed`. The plan asked for work that turned out not to be possible as
  specified. The most interesting of the three: somebody attempted it and found out.
- An item ended `skipped` because it reached execution still blocked on an unanswered decision.
  The plan was right to escalate; the gap is that the question survived the review sitting.
- A declared coverage delta was never measured because the item declaring it never ran.

**Not this.** An item that failed because the code was broken in a way nobody could have
foreseen. That is a defect, and the plan was fine.

### 2. `assessment-staleness`

**Recognition test.** An item's target had moved between the assessment and the run — pre-flight
marked it `stale`.

The cost is what those items would have asserted and now do not, and the finding names those
claims. Repeated staleness across runs measures something worth measuring: how long an
assessment stays usable in this repository, which is the number that decides whether the
assess-plan-execute cycle is short enough for the rate the code changes.

**Not this.** An item that failed because the code changed *during* the run. That is an
execution problem, and it belongs to `tooling-defect` if anything.

### 3. `planner-claim-accuracy`

**Recognition test.** The planner said the code did something and it did not.

Three sources, and all three measure the same thing from different angles:

- **Disputes.** A pinned claim that a faithful test contradicted. The claim's only backing was
  the planner's reading, and the reading did not hold.
- **Verifier rejections.** A fresh-context verifier ruled a test unfaithful to its claim, or
  too weak to discriminate it.
- **Mutation checks that failed.** The named edit did not make the named test fail, so the
  suite would not notice the behavior changing — which is the property the check exists to
  establish.

This is the category with the most riding on it across runs. Stage two derives pinned claims at
scale, on the argument that reading behavior out of code is cheap and useful. This finding is
the only thing that measures how often that reading is wrong, and until something counted it
there was no way to know whether the argument holds.

**Not this.** A cited claim the code contradicts. That is a defect: the document said so, and
the planner quoted the document correctly.

### 4. `footprint-accuracy`

**Recognition test.** An item's commit touched files its declared footprint did not name, or
declared files it never touched.

Both directions matter and they cost differently. **Touching what was not declared** is an
item failure under execution R-2.2 and a direct reason not to enable concurrent execution:
slices scheduled as disjoint were not. **Declaring what was never touched** costs nothing at
execution time and does cost the wave computation, which schedules on declared footprints and
therefore serialises slices that never needed to be.

Planning R-10.3 defers concurrent execution until these agree across real plans. The ledger's
`footprint_accuracy` array is where the history accumulates, and it accumulates whether or not
a finding is raised — a run where every item came out exact is data, not a finding.

### 5. `tooling-defect`

**Recognition test.** A script, a schema, or a check did not do its job, and would not have on
any repository.

Sources:

- An R-4.2 consistency check failed: the run summary and the plan writeback disagree.
- A completion check was reported `not-run` — the runner could not execute it, so what it would
  have established is unknown rather than established.
- A coverage delta declared by an item that *completed* has no measured figure. The work ran
  and the measurement did not.
- The suite could not be measured at close-out.

**Not this.** A check that ran and failed. That is the check working.

## Numbering, and what recurrence means

Identifiers are `PF-01` upward, assigned by `findings.py` and reconciled against the ledger
before they are issued.

The reconciliation is by **signature** — the category plus the identifiers the finding is about
— rather than by the summary text. Two runs derive their findings independently from their own
records, so recognising the same problem twice needs a key both derivations produce, and a
reworded sentence would otherwise look like a new problem. That is precisely the failure the
recurrence flag exists to catch.

Numbers are never reused. The next number comes from the highest ever issued, not from the
count of what is open, so a reader who finds `PF-03` in an old report and `PF-03` in a new one
is reading about the same thing.

**A recurring finding is worth more attention than a new one.** A new finding is a thing that
went wrong once. A finding on its third run without being retired or contested is a thing the
pipeline reliably produces, and reliably-produced problems are what requirements amendments are
for. Write the recurring ones first in the report's prose, with their run counts.

## Retirement

Explicit, and it names the change that addressed it:

```bash
python3 ledger.py docs/test-ledger.json --retire-finding PF-03 \
        --by "slice sizing heuristic amended; planning changelog 2026-08-09"
```

A finding that stops appearing because nobody looked is still open, and the ledger keeps
re-reporting it until somebody says otherwise. That is the same discipline R-7.2 applies to
defects, and it exists for the same reason: silence and resolution look identical from the
outside.

Contesting is the other way out — `--contest PF-03 --note "..."` — for a finding that was
mis-derived or that describes intended behavior. It is a disposition, not a dismissal: the note
is what a later reader gets instead of the finding.

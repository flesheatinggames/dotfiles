# The Execution Writeback

**Nothing in this document is written by the planner.** Every field and block described here
is written by stage three, the execution skill, into the plan file the planner produced. They
are specified here, in stage two's schema, for one reason: stage three's own entry gate is
`plan_lint.py`, so a field this linter does not know is a field the executor cannot write. An
`actuals:` mapping with no schema is not undefined — it is a `field-unknown` failure that
makes the writeback impossible.

The planner's obligation is therefore small and entirely negative: **do not write any of
this.** The linter enforces that at `--phase planned` and `--phase reviewed`, reporting
`premature-execution-block`, `premature-execution-field`, and `premature-approval`.

`fixtures/executed-plan.md` in the `code-coverager` repository is the worked reference: a
complete run recorded against `fixtures/synthetic-plan.md`, carrying every terminal status in
the vocabulary.

---

## Why the plan file is the running record

Stage two established the plan as the document the stage four report is built from. Stage
three could have written a separate results file and left the plan untouched, and that would
have been easier. It would also have meant two documents that can disagree about what
happened, and the one a person opens is the plan.

So execution writes back into the plan, in place, preserving the comments the owner added at
review. That is what the line spans in `planlib.py` are for — `MapNode.line_of()` and
`value_spans` record the file line of every key so a single `status:` line can be rewritten
without disturbing a byte around it.

**Bulk goes to a sidecar.** Full failure output, preserved diffs, and dispute evidence go to
`docs/test-execution-log/` and are referenced from the plan by path (execution R-9.2). The
plan stays readable; the evidence stays complete.

---

## The approval field

```yaml
approved:
  by: "R. Okonkwo"
  date: "2026-07-31"
  note: >
    Approved with E1 answered and DEC-01 left open. The coverage number is not approved with
    the plan.
```

Written by the **owner** at the review sitting, not by the planner and not by the executor.
Execution R-4.1 reads this field and nothing else: an unapproved plan is never executed.

**This is not `target.approved`, and keeping them apart is deliberate.** `target.approved`
approves a coverage number. This approves the plan. An owner may perfectly well approve the
plan while deferring the number — that is exactly the case `form: delta-with-rederivation`
models, where slice zero changes the denominator and a target approved beforehand was
approved against a figure about to stop meaning what it meant.

**The field is `date`, not `on`.** A bare `on:` key is the boolean `True` to PyYAML's YAML
1.1 resolver, so `{by, on, note}` parses one way here and another way there, and the R-11.1
cross-check reports it as a parser disagreement rather than as the field-naming mistake it
is. The bundled parser now rejects the whole family of ambiguous keys — `on`, `off`, `yes`,
`no` — with a message saying so. Quoting the key would also work and is worse: the quotes
become load-bearing, and the next person to tidy them away breaks the plan.

---

## Fields on a work item

| Field | Written when | Holds |
|---|---|---|
| `status` | Throughout | Rewritten in place. `in-progress` at the start, then a terminal value |
| `commit` | On completion | The commit the item's work landed in |
| `actuals` | On completion, or on a failure worth recording | What the repository says happened, never self-report |
| `diagnosis` | On `failed`, `stale`, or `blocked-by-failure` | Why the item did not complete |

### `actuals`

```yaml
actuals:
  started: "2026-08-01T11:37:20Z"
  finished: "2026-08-01T14:22:05Z"
  attempts: 3
  files_touched:
    production: []
    test:
      - tests/test_money_parse.py
    config: []
  checks:
    - kind: mutation
      claim: C1
      outcome: suspended
      detail: >
        Suspended under R-7.4 because C1's test is standing red in the defect registry.
    - kind: coverage-delta
      outcome: passed
      detail: "ledger/money.py line coverage 74 to 94, against the target of 92."
```

`files_touched` carries an underscore where the declared `files-touched` carries a hyphen,
and the near-collision is the point rather than an oversight: the two fields exist to be
compared, and the whole reason for recording the second is that it can differ from the first.
The declared one is what the planner promised; this one is measured from the git diff of the
item's commit.

**`kind` accepts three values the authored check catalog does not**, because nothing authors
them. `coverage-delta` is an implied check generated from the item's own field.
`claim-annotations` is generated from the item's `claims` list. `standing-invariant` runs on
every item whether it asks for one or not.

**Any outcome other than `passed` requires a `detail`.** Execution R-10.2 forbids inferring a
check: one the runner could not execute is reported `not-run` and never guessed at, and a
failure nobody explained is a failure nobody can act on. The linter reports the omission as
`check-outcome-unexplained`.

### The footprint rule is a failure, not an edit

If an item touched a file its declared footprint does not name, the linter reports
`footprint-exceeded` and the item fails. It does **not** get to widen `files-touched` to
match — that field is planner content, and execution R-2.1 does not list it among the fields
the executor may write.

The reason is that planning R-10.3 gates any future concurrent execution on declared
footprints matching actual ones. That measurement is worth nothing if the executor may edit
the declaration to make it true, which is why R-2.2 states the prohibition and why the linter
checks it from the other side.

---

## The blocks

### `execution-log` — one per attempt

```yaml execution-log
item: WI-04
attempt: 3
outcome: passed
summary: >
  Committed the C1 case red under R-7.2 and registered DF-1.
verifier:
  - brief: faithfulness
    verdict: faithful
    date: "2026-08-01"
    note: >
      Fresh context, given only C1's text and the test.
log: docs/test-execution-log/WI-04-attempt-3.txt
preserved-diff: execution/WI-05-dispute
```

Every attempt gets one, **including the attempt that worked first time**. `outcome` is about
the attempt rather than the item: `checks-failed`, `reverted`, and `abandoned` are all normal
entries in a run that ended well. `attempt` numbers are distinct within an item, and their
count must equal `actuals.attempts` — the log is the evidence and the count is a summary of
it, so a disagreement means one of the two writes was lost.

### `defect` — the registry of execution R-7.2

```yaml defect
id: DF-1
claim: C1
item: WI-04
observed: >
  parse_amount ignores the active locale's decimal separator entirely.
test:
  file: tests/test_money_parse.py
  name: test_parse_amount_reads_the_german_separator
verification:
  brief: faithfulness
  verdict: faithful
  date: "2026-08-01"
  note: >
    Fresh-context verification against C1's text alone.
commit: 1d9f8e2
suspended-mutations:
  - C1
resolution: null
```

A defect is the code contradicting a claim somebody made binding, and its committed red test
is the enforcement mechanism: it blocks the pipeline until a recorded decision is made about
it, which is the point rather than a side effect.

Four rules the linter holds it to, each guarding a different way the mechanism can be
subverted:

- **The claim must be `cited`, `ratified`, or `ratified-as-observed`.** This is the asymmetry
  of R-7.2 against R-7.5, and it is the subtlest thing in stage three. A defect belongs to a
  claim carrying a document's authority or the owner's personally. A failing test of a
  `pinned` claim impeaches the planner's reading instead — it becomes a dispute, and commits
  nothing. Registering it as a defect would block deploys over a fiction. Reported as
  `defect-claim-not-cited`.
- **The item must be `done-with-defect`.** The executor wrote the test the claim describes and
  the test failed, so the work was done correctly and the code is what is wrong. Reported as
  `defect-item-not-done-with-defect`.
- **`verification.brief` must be `faithfulness` and `verification.verdict` must be
  `faithful`.** R-7.3 is unconditional: no red test stands until a fresh-context verifier,
  given only the claim's text and the test, confirms the test asserts the claim. A
  deploy-blocking red raised over the executor's own misreading is the worst false alarm this
  stage can produce.
- **`resolution` stays null until close-out.** It is the owner's answer at stage four.
  Downgrading a defect is reserved to whoever made the claim binding, never to an agent
  mid-run (R-2.5).

`suspended-mutations` lists the claims whose mutation checks are waiting for this test to go
green. Mutating code against an already-failing test proves nothing, so those checks are
recorded `suspended` rather than passed (R-7.4), and the linter reports a `passed` mutation
against a registry claim as `mutation-not-suspended`.

### `run-summary` — one per plan

The forward interface onto stage four (R-9.3): items by final status, claims by final state,
defects, disputes, coverage before and after, footprint diffs, inherited failures, and every
way the run narrowed its own scope.

**It is derived, not authored**, and the linter recomputes the item, defect, and dispute
lists from the plan and fails on a disagreement — `run-summary-disagrees`. A summary that has
drifted from the statuses beneath it would be believed, and drift is exactly what a late
status change produces.

`narrowings` is where execution R-10.3 lands: a partial run that reports honestly is a
success mode, and only silent omission is failure. Each entry says what was narrowed **and
what the narrowing cost**, in the same shape planning R-13.3 asks of inherited degradations.

---

## The order of writes, which is load-bearing

Stage three re-lints after every write and rolls back anything that fails. Intermediate states
therefore have to lint clean, and that constrains the order in ways the rules above imply but
do not state:

1. `status: in-progress`
2. the work
3. append the `execution-log` block for the attempt
4. write `actuals` and `commit`
5. write the terminal `status`
6. only then append any `defect` block — it requires its item to be `done-with-defect`

For a dispute the order inverts around the claim:

1. write the item's `diagnosis`
2. write `status: failed`
3. write the claim's `evidence`
4. only then write `label: disputed` — it requires both the evidence and the failed item

Writing a `disputed` label before its evidence fails `disputed-without-evidence` and gets
rolled back, which is a correct outcome and a confusing one to debug. The execution skill's
`references/writeback.md` states this order as procedure; it is repeated here because the
rules that force it live in this schema.

# Work Item Schema

Every field, its legal values, and a worked example per type. The machine-readable version of
this is in `scripts/planlib.py`; `references/schema/plan-yaml.md` defines the YAML subset and
`references/schema/completion-checks.md` defines the check catalog.

A work item is the atomic unit of planned work. It exists so that stage three can perform it
without deciding anything about *what* to build.

## The five types

R-7.1 originally named four. A fifth was added because four do not fit real work.

| Type | Does | Carries claims? |
|---|---|---|
| `infrastructure` | Installs or configures tooling | No |
| `characterization` | Pins current behavior to guard a refactoring | No |
| `seam` | Makes a piece of behavior reachable by a unit test | Via `claims-enabled` |
| `unit-tests` | Writes tests asserting claims | Yes, in `claims` |
| `test-repair` | Changes existing tests so they can fail | Yes, in `claims` |

### Why `test-repair` is its own type rather than `infrastructure`

Four of one real repository's five recommendations do not fit the original enum. One adds
assertions to eight existing, passing test files. Another deletes a file containing sixty-one
placeholder tests that report green. Neither writes a new test and neither installs anything.

Overloading `infrastructure` would work mechanically and would break stage four, which has to
report "tests repaired" separately from "tests written". For a repository whose central
problem is that its tests cannot fail, that is the first question its owner will ask, and a
report that cannot answer it has lost the thing the plan was for.

`test-repair` also carries a rule the other types do not, though it now shares it with
`unit-tests`: every claim it asserts must be covered by a mutation check or a waiver. A repair
whose purpose is assertion strength passes every other check type whether it was done well,
badly, or not at all — coverage does not move, the files still exist, and the tests still
pass. A repair that instead *removes* tests carries no claims and so has nothing to cover; it
verifies the removal with a `pattern-count` expecting zero or a `file-exists` marked absent.

---

## Fields

### Always required

| Field | Type | Notes |
|---|---|---|
| `id` | string | `WI-` and at least two digits. Stable across plan revisions, because status writeback and dependency references both rely on it |
| `type` | string | One of the five above |
| `slice` | string | `S` and digits. The slice must list this item, and the linter checks both directions |
| `title` | string | At least ten characters. What a person would call this piece of work |
| `assessment-ref` | list | Identifiers from the assessment index — `F`, `R`, `X`, `D`, or `Q`. At least one. An item descending from nothing in the assessment is out of scope for this plan |
| `target` | list of mappings | Each `{file, functions?, lines?, note?}`. Concrete, repository-relative |
| `depends-on` | list | Item identifiers. `[]` when there are none — never omitted |
| `files-touched` | mapping | `{production, test, config}`, each a list. The declared footprint |
| `global-effect` | boolean | See below |
| `completion-checks` | list | At least one, from the closed catalog |
| `effort` | mapping | `{unit, value}`. `unit` is `hours` or `sessions` |
| `risk-tier` | string | `top`, `high`, `medium`, or `low`. Inherited from the assessment |
| `status` | string | `pending` or `blocked-on-decision` in a fresh plan |

### Conditional

| Field | Required when | Notes |
|---|---|---|
| `claims` | `unit-tests` always; `test-repair` unless it removes tests | Claim identifiers. Forbidden on `infrastructure`, `characterization`, and `seam`. A repair that deletes worthless tests has no claims to carry and must instead verify the removal, with a `pattern-count` expecting zero or a `file-exists` marked absent |
| `claims-enabled` | Optional, `seam` only | Claims this seam unlocks, carried by a later item |
| `seam-type` | `seam` | 1–4 from the closed catalog. Forbidden on every other type |
| `guarded-by` | `seam`, unless waived | The characterization item guarding it. Must also appear in `depends-on` |
| `guard-waiver` | `seam` without `guarded-by` | Why no guard is required, in writing |
| `blocked-by` | `status: blocked-on-decision` | Escalation or decision identifiers. Forbidden otherwise |
| `coverage-delta` | Optional | Expected movement per file. **Every entry is an implied completion check**; there is deliberately no `coverage-delta` check kind, because two copies of one statement drift and did |
| `mutation-waiver` | Any asserted claim with no mutation check | One entry per waived claim, each with a `claim` and a `reason` of at least forty characters |
| `justification` | Deviations | At least twenty characters |
| `notes` | Optional | Free text |

### Written by stage three, never by the planner

| Field | Written when | Holds |
|---|---|---|
| `commit` | On completion | The commit the item's work landed in |
| `actuals` | On completion | `{files_touched, checks, started, finished, attempts}`, measured from the repository rather than self-reported |
| `diagnosis` | On `failed`, `stale`, or `blocked-by-failure` | Why the item did not complete |

These are in the schema because stage three's own entry gate is this linter: a field the
linter rejects is a field the executor cannot write. Writing one into a fresh plan is the
failure `premature-execution-field` catches, and it is the same mistake as writing a `done`
status or a `ratified` claim — reporting on work that has not happened.

`references/schema/execution-writeback.md` specifies all three, plus the `execution-log`,
`defect`, and `run-summary` blocks and the `approved` field on `plan-meta`.

Any other field name is a lint failure. A misspelled `justifcation` that was silently ignored
would produce a plan that lints clean while missing the justification a deviation requires.

### Every asserted claim carries a mutation check or a waiver

A `unit-tests` or `test-repair` item must, for each claim in its `claims` list, either carry
a `mutation` completion check naming that claim, or one `mutation-waiver` entry naming it.
Never both, and never neither.

```yaml
claims: [C12, C13, C18]
completion-checks:
  - kind: mutation
    claim: C12
    file: lib/actions/organizer-dashboard.ts
    mutation: "Delete the `.eq('user_id', user.id)` filter at line 476."
    command: "npx jest __tests__/organizer-dashboard.test.ts --ci"
    expect: named-tests-fail
    tests: ["markNotificationRead scopes its update to the calling user"]
    restore: "git checkout -- lib/actions/organizer-dashboard.ts"
  - kind: mutation
    claim: C13
    file: lib/actions/organizer-dashboard.ts
    mutation: "Change the `read_at` payload to a fixed literal rather than the current time."
    command: "npx jest __tests__/organizer-dashboard.test.ts --ci"
    expect: named-tests-fail
    tests: ["markNotificationRead records when the notification was read"]
    restore: "git checkout -- lib/actions/organizer-dashboard.ts"
mutation-waiver:
  - claim: C18
    reason: >
      The claim is that the module exports exactly these four names. No edit to the module
      body falsifies it, because the shape rather than the behavior is what is asserted.
```

Note the folded block scalar on `reason`. The plan's YAML subset does not accept a quoted
scalar spanning two lines; write `>` and indent the body.

This is the obligation that most often makes a plan fail lint on its first draft, and that
is the intended behavior rather than an inconvenience. The rule it replaced asked only that
a `test-repair` item carry a mutation check somewhere, which one check on a twelve-claim
item satisfied while verifying one claim.

`references/schema/completion-checks.md` gives the mutation patterns each claim shape
implies, and the standard the waiver's reason is held to.

The exemption for a repair that removes tests is unaffected: it carries no claims, so there
is nothing to cover.

### `global-effect`

True when the item changes something with repository-wide effect even though its declared
footprint is small.

R-10.2 defines a wave as a set of slices with pairwise disjoint footprints and no dependency
edges. Slice zero breaks that definition: its footprint is one configuration file, and
rewriting the coverage configuration changes what every other slice measures. A footprint-only
rule would schedule other slices alongside it. `global-effect: true` makes the slice occupy a
wave alone.

Set it for coverage configuration, test runner configuration, shared test setup files, and
anything else whose effect is not confined to the files it edits.

### `claims-enabled` versus `claims`

A seam does not assert anything. It makes assertions possible. If a seam carried the claims it
unlocks, those claims would appear twice on the ratification list — once on the seam, once on
the unit-test item that actually asserts them — and the owner would be asked to approve each
twice.

So a seam uses `claims-enabled`, which points at claims defined elsewhere and counted once.
The linter rejects `claims` on a seam and `claims-enabled` on anything else.

### `effort` needs a unit

R-8.4 says slices are sized to fit a single working session. That is only checkable if the
estimate has a unit. `{unit: hours, value: 3}` can be summed against a session; `3` cannot.

`sessions` is available for items too large to estimate in hours, and an item of more than one
session is a sign the item should be split.

---

## Worked examples

### `infrastructure`

Slice zero, degraded to verify-and-baseline because a framework already exists.

```yaml work-item
id: WI-01
type: infrastructure
slice: S0
title: "Verify the suite runs and write the exclusion list into the coverage configuration"
assessment-ref:
  - X1
  - X2
target:
  - file: pyproject.toml
    note: "the [tool.coverage.run] omit list"
depends-on: []
files-touched:
  production: []
  test: []
  config:
    - pyproject.toml
global-effect: true
completion-checks:
  - kind: tests-pass
    command: "python3 -m pytest --cov=ledger --cov-report=xml"
    expect: all-pass
  - kind: file-exists
    path: coverage.xml
effort:
  unit: hours
  value: 1
risk-tier: high
status: pending
justification: >
  Slice zero normally installs a test framework. Here one exists, so the item degrades to
  verifying it runs and fixing the denominator. Skipping the slice entirely would leave every
  coverage delta in this plan stated against a baseline that is about to change.
```

### `characterization`

Scaffolding, removed once real tests cover the behavior. Carries no claims, because pinning
current behavior is not asserting that it is correct — which is exactly what makes it safe to
write before anybody has agreed what correct means.

```yaml work-item
id: WI-02
type: characterization
slice: S1
title: "Characterize parse_amount at its current boundary before the locale seam"
assessment-ref:
  - R1
target:
  - file: ledger/money.py
    functions:
      - parse_amount
    lines: "12-33"
depends-on:
  - WI-01
files-touched:
  production: []
  test:
    - tests/characterization/test_parse_amount.py
  config: []
global-effect: false
completion-checks:
  - kind: file-exists
    path: tests/characterization/test_parse_amount.py
  - kind: tests-pass
    command: "python3 -m pytest tests/characterization/test_parse_amount.py"
    expect: all-pass
effort:
  unit: hours
  value: 2
risk-tier: top
status: pending
notes: >
  The assessment records that the current locale decides two of the four expected results, so
  this test sets the locale explicitly.
```

### `seam`

Names a catalog seam type, depends on its guard, and carries a `guard-holds` check. All three
are enforced: a guard that is not a dependency does not get written first, and a guard whose
passing is not a completion condition was not worth writing.

```yaml work-item
id: WI-03
type: seam
slice: S1
title: "Wrap the locale read behind a substitutable separator source"
assessment-ref:
  - R1
  - F2
target:
  - file: ledger/money.py
    functions:
      - parse_amount
    lines: "12"
claims-enabled:
  - C1
  - C2
seam-type: 3
guarded-by: WI-02
depends-on:
  - WI-02
files-touched:
  production:
    - ledger/money.py
  test: []
  config: []
global-effect: false
completion-checks:
  - kind: guard-holds
    item: WI-02
    command: "python3 -m pytest tests/characterization/test_parse_amount.py"
  - kind: tests-pass
    command: "python3 -m pytest"
    expect: all-pass
effort:
  unit: hours
  value: 2
risk-tier: top
status: pending
```

### `unit-tests`

```yaml work-item
id: WI-04
type: unit-tests
slice: S1
title: "Unit tests for parse_amount across separator styles and the empty input"
assessment-ref:
  - F2
target:
  - file: ledger/money.py
    functions:
      - parse_amount
    lines: "12-33"
claims:
  - C1
  - C2
depends-on:
  - WI-03
files-touched:
  production: []
  test:
    - tests/test_money_parse.py
  config: []
global-effect: false
completion-checks:
  - kind: file-exists
    path: tests/test_money_parse.py
  - kind: tests-pass
    command: "python3 -m pytest tests/test_money_parse.py"
    expect: all-pass
coverage-delta:
  - file: ledger/money.py
    metric: lines
    from: 74
    to: 92
    baseline-source: slice-zero
effort:
  unit: hours
  value: 3
risk-tier: top
status: pending
```

### `test-repair`

The mutation check is what makes this item checkable at all. Note the justification: it says
plainly that coverage will not move, which is the finding rather than a shortcoming.

```yaml work-item
id: WI-06
type: test-repair
slice: S3
title: "Add real assertions to the twelve claims-free tests in test_report.py"
assessment-ref:
  - F5
target:
  - file: tests/test_report.py
    lines: "22-96"
  - file: ledger/report.py
    functions:
      - render_summary
claims:
  - C6
  - C7
depends-on:
  - WI-01
files-touched:
  production: []
  test:
    - tests/test_report.py
  config: []
global-effect: false
completion-checks:
  - kind: tests-pass
    command: "python3 -m pytest tests/test_report.py"
    expect: all-pass
  - kind: mutation
    claim: C6
    file: ledger/report.py
    mutation: "Change the amount column width at ledger/report.py:88 from 12 to 10."
    command: "python3 -m pytest tests/test_report.py"
    expect: named-tests-fail
    tests:
      - "test_render_summary_formats_a_single_entry"
    restore: "git checkout -- ledger/report.py"
  - kind: mutation
    claim: C7
    file: ledger/report.py
    mutation: >
      Delete the `if entry.void:` branch at ledger/report.py:103 so voided entries are
      rendered like any other.
    command: "python3 -m pytest tests/test_report.py"
    expect: named-tests-fail
    tests:
      - "test_render_summary_omits_voided_entries"
    restore: "git checkout -- ledger/report.py"
effort:
  unit: hours
  value: 3
risk-tier: medium
status: pending
justification: >
  Coverage of ledger/report.py does not move, because every line these tests reach is already
  counted as covered. That is the point of the finding, and it is why this item carries
  mutation checks: without them, the item would satisfy every other check type whether it was
  done well, badly, or not at all.
```

Note the two mutation checks rather than one. The item asserts C6 and C7, so it covers both.
One check naming C6 would leave C7 asserted by a test nobody has shown can fail, which is the
same problem the item exists to fix.

### A blocked item

Everything about it is written out, including what it would do, so the owner can see what
answering the question costs either way.

**A blocked item is written as one answer, not as an average of them.** Where the answers
imply different work, each alternative carries its own rewrite on the blocking option, using
the `effect` field described in `references/conflict-catalog.md`. The item's justification
says which answer the written form is. Putting the difference in the item's prose instead
makes it two pieces of work wearing one identifier, and the linter rejects it.

```yaml work-item
id: WI-05
type: unit-tests
slice: S2
title: "Unit tests for round_balance's scale and sign symmetry"
assessment-ref:
  - F1
  - R3
target:
  - file: ledger/money.py
    functions:
      - round_balance
claims:
  - C4
  - C5
depends-on:
  - WI-01
files-touched:
  production: []
  test:
    - tests/test_money_round.py
  config: []
global-effect: false
completion-checks:
  - kind: tests-pass
    command: "python3 -m pytest tests/test_money_round.py"
    expect: all-pass
effort:
  unit: hours
  value: 2
risk-tier: top
status: blocked-on-decision
blocked-by:
  - E1
justification: >
  Blocked because C4 and C5 deliberately say nothing about which rounding mode is correct, and
  a test that pins the mode would enshrine whichever side it asserted. Once E1 is answered, one
  further claim covering the mode is added and this item executes.
```

---

## Status

| Value | Means | Written by |
|---|---|---|
| `pending` | Ready to execute | The planner |
| `blocked-on-decision` | Waiting on an escalation or decision | The planner |
| `in-progress` | Started | Stage three |
| `done` | Completed, every check passed | Stage three |
| `skipped` | Not attempted — usually because its blocker went unresolved | Stage three |
| `failed` | Attempted, and a completion check did not pass | Stage three |
| `done-with-defect` | Implemented correctly, and it surfaced a defect in the production code | Stage three |
| `blocked-by-failure` | A dependency failed, so this was never reached | Stage three |
| `stale` | The target moved between planning and execution | Stage three |

**`failed` is distinct from `skipped` and both are needed.** An item nobody attempted because
the owner left its escalation open, and an item somebody attempted whose mutation check kept
passing, are different facts about the run. Collapsing them into one state loses the second,
which is the more interesting one: it means the plan asked for something that turned out not
to work.

**`done-with-defect` is not a failure.** The executor wrote the test the claim describes, the
test failed, and the test is faithful — so the item was done correctly and the code is what
is wrong. Marking it `failed` would blame the work for finding the thing it was written to
find, and the stage four report would then be unable to distinguish a plan that did not work
from a plan that worked and surfaced a bug.

A freshly written plan contains only the first two. The linter rejects every other value
unless it is told the plan has been executed (`--phase executed`), because a plan arriving
with an item marked `done` is a plan reporting on work that has not happened.

These statuses live in the plan's schema rather than the executor's because the plan file is
the running record the stage four report is built from. A status the linter rejects is a
status the executor cannot write.

---

## Claim labels

Claims are defined once, on the ratification list, and referenced by identifier. Their labels
are phase-gated the same way statuses are.

| Value | Means | Written by |
|---|---|---|
| `cited` | Traced to a requirements or specification document, with location and quote | The planner |
| `pinned` | Inferred from the code; documents current behavior nobody has ratified | The planner |
| `ratified` | A pinned claim the owner approved at the review sitting | The owner |
| `disputed` | A pinned claim whose faithful test failed, impeaching the planner's reading | Stage three |
| `ratified-as-observed` | A cited claim the owner ruled wrong at close-out, accepting observed behavior instead | The owner, at close-out |

**A dispute is about a pinned claim, never a cited one.** When a cited claim's faithful test
fails, the document's authority stands and the code is what is wrong: that is a defect, and
it produces a registry entry and a committed red test. When a pinned claim's faithful test
fails, the claim's only backing was the planner's reading, so the failure impeaches the
reading — evidence is captured, the claim is marked `disputed`, and nothing red is committed.
A red test asserting behavior that never existed would block deploys over a fiction.

`ratified-as-observed` is the close-out counterpart: the owner has decided the requirement
itself was wrong, the test is rewritten to assert the observed behavior as an ordinary green
test, and the report flags the document for amendment.

---

## `known-defects` — naming what is already broken in a file you plan to touch

Optional, and required only when the repository has a run ledger holding an open defect
against a file this item's footprint names. `plan_lint.py --ledger` says which item owes which.

```yaml
known-defects:
  - DF-1
```

R-7.3 of the reporting requirements obligates the planner to consistency with the run ledger
rather than to itemised discharge. **You may plan nothing at all about an open defect** —
fixing it may be somebody else's work, or scheduled for a later cycle, and a plan is a proposal
rather than a statement about the repository's state.

What is never legitimate is planning work *on top of* one without saying so. The executor will
write tests in a file where something is already known to be broken, and this field is the only
way it finds out. Without it a failing test in that file reads as a new defect, and the run
registers a second entry for a problem the ledger already carries.

The counterpart obligation on stage one is much heavier — every open ledger item confirmed,
updated, or contested — and the asymmetry is deliberate. An assessment establishes a
repository's state, so an item absent from one has been asserted not to exist.

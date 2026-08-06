# Completion Checks — The Closed Catalog

Every work item carries at least one completion check. A check must be **machine-checkable
as written** (R-7.1): a script must be able to run it and get a yes or a no without asking
anyone what was meant. "Tests are adequate" is not a check. "The command
`npx vitest run src/lib/__tests__/product-loader.test.ts` exits zero" is.

**This catalog is closed.** Five kinds. A check that fits none of them means either the work
item is not well enough specified to execute, or the plan is trying to promise something it
cannot verify. Both are worth discovering at lint time.

**"As written" excludes prose that qualifies the check.** A `mutation` check followed by a
sentence saying it applies only under one answer to a decision is not machine-checkable,
because the executor has to read the sentence and decide. Where an item's checks differ by
the answer to a decision it is blocked on, the difference belongs in that answer's `effect`
— see `references/conflict-catalog.md`. The linter reports the prose version of this as
`conditional-prose`.

---

## Why there are five, and why coverage delta is not one of them

R-7.1 named four kinds: named test files exist, named tests pass, the coverage delta
materialised, and the guarding characterization tests still pass after a seam. Two were
added because the original four cannot check the work with the highest value, and one was
removed because it duplicated a field.

**Coverage delta is a field on the work item, not a check kind.** It behaves like a check,
and R-7.1 already frames it as one — "stated per file, as a completion check rather than a
goal" — but it was also a field, and two copies of one statement drift. They drifted inside a
single writing session: four items declared a delta for two files each and wrote the check for
only one of them, and one item wrote the check with no field at all, so the delta would have
vanished if the field were taken as the record. Every entry in the `coverage-delta` field is
now an implied completion check, and writing `kind: coverage-delta` is a lint failure whose
message says where it went.

**All four original kinds are satisfied by an item that changes nothing meaningful.** Take
`sbcf-app`'s central problem: eight test files whose mocks resolve identically regardless
of which authorization filter was applied, so deleting a filter leaves all 39 covering
tests green. The work item that fixes this adds assertions to tests that already exist and
already pass. Afterwards: the files still exist, the tests still pass, coverage has not
moved by a single line, and there is no seam to guard. Every original check passes whether
the item was done properly, done badly, or not done at all.

The `mutation` check is the only one that verifies what that plan is actually for. It
reuses the backup-and-restore protocol already written down in the assessment skill's
`references/parallel-reading.md`, under which one real assessment proved its central
finding rather than arguing it.

`pattern-count` was added for the opposite shape: an item whose completion means something
is *gone* — a deleted placeholder file, a removed `expect(true).toBe(true)`, a dead
function. Absence is checkable and none of the original four checks it.

---

## 1. `file-exists`

The named file exists after the item is done.

```yaml
- kind: file-exists
  path: src/lib/__tests__/product-loader.test.ts
```

| Field | Required | Meaning |
|---|---|---|
| `path` | yes | Repository-relative path |
| `absent` | no | `true` inverts the check: the file must *not* exist. Use for a deletion item |

Weak on its own — an empty file passes. Pair it with `tests-pass`.

---

## 2. `tests-pass`

The named command exits zero, and the named tests are among the ones it ran.

```yaml
- kind: tests-pass
  command: "npx vitest run src/lib/__tests__/product-loader.test.ts"
  tests:
    - "parseProductOverview returns null for an empty document"
  expect: all-pass
```

| Field | Required | Meaning |
|---|---|---|
| `command` | yes | Run from the repository root. Repository-relative paths only |
| `tests` | no | Test names that must appear in the run and pass. Naming them is what stops a passing run of zero tests from satisfying the check |
| `expect` | yes | `all-pass` or `named-tests-fail`. The second is for a check that deliberately expects failure, such as the negative half of a mutation |

**Never write an absolute path into `command`.** A block containing `/Users/someone/…` is
not reproducible by anyone else or on any other machine, which defeats the point. This
mistake has already been made once in this suite's output.

---

## The coverage delta field

Not a check kind. A field on the work item, every entry of which is an implied check.

```yaml
coverage-delta:
  - file: src/lib/product-loader.ts
    metric: lines
    from: 0
    to: 60
    baseline-source: slice-zero
```

| Field | Required | Meaning |
|---|---|---|
| `file` | yes | Repository-relative |
| `metric` | yes | `lines`, `branches`, `functions`, or `statements` |
| `from` | yes | The baseline percentage |
| `to` | yes | The target percentage. Must exceed `from` |
| `baseline-source` | yes | Where the `from` figure comes from. See below |

**`baseline-source` is not bookkeeping**, and the three values are not interchangeable.

- **`assessment-index`** — the assessment recorded this file's figure *and* its
  `coverage_baseline.files_complete` flag is true. Where that flag is false, a file the
  assessment did not name has no recorded baseline and writing one is a fabrication.
- **`slice-zero`** — the baseline exists only once slice zero has run. **This is the usual
  answer, and on a repository with no suite it is the answer for every file that already
  exists.** Slice zero precedes every other item, so a baseline exists by the time any delta
  is checked. Reasoning that "zero is true by construction because there are no tests" is the
  trap: it is true of the code today and not of the measurement the check will run against.
- **`none`** — reserved for a file that **does not exist when slice zero runs** and is created
  by this plan, typically the target of an extraction seam. There zero really is true by
  construction, because there is no file to measure.

**`none` is a paired rule and the linter checks both halves.** It is legal only alongside
`from: 0`, and the entry's `note` must say that this plan creates the file:

```yaml
coverage-delta:
  - file: ledger/formatting.py
    metric: lines
    from: 0
    to: 90
    baseline-source: none
    note: >
      WI-04 creates this file by extracting from ledger/report.py, so it does not exist
      when slice zero measures.
```

Either half without the other is a failure. A `none` beside a non-zero starting figure claims
to have no baseline while stating one. A `none` with no note is the shape this field takes
when a planner reaches for it to avoid recording where the number came from — which is the
only reason the value is constrained at all, since it is otherwise the easiest of the three
to write.

A coverage delta is stated as a check rather than as a goal (R-7.1) because a goal is
something to feel bad about and a check is something to run.

---

## 3. `guard-holds`

The characterization tests that guard a seam still pass after the refactoring.

```yaml
- kind: guard-holds
  item: WI-04
  command: "npx vitest run src/lib/__tests__/loaders.characterization.test.ts"
```

| Field | Required | Meaning |
|---|---|---|
| `item` | yes | The characterization work item whose tests are the guard |
| `command` | yes | How to run them |

Required on every `seam` item that has a `guarded-by`. This is the check that makes a seam
recommendation safe to execute rather than merely recommended.

---

## 4. `mutation`

A named change to production code makes named tests fail. The item is complete when the
suite can detect the defect it was written to detect.

```yaml
- kind: mutation
  claim: C12
  file: lib/actions/organizer-dashboard.ts
  mutation: "Delete the `.eq('user_id', user.id)` filter at line 476."
  command: "npx jest __tests__/organizer-dashboard.test.ts --ci"
  expect: named-tests-fail
  tests:
    - "markNotificationRead scopes its update to the calling user"
  restore: "git checkout -- lib/actions/organizer-dashboard.ts"
```

| Field | Required | Meaning |
|---|---|---|
| `claim` | yes | The claim this edit falsifies. Must be one the item asserts |
| `file` | yes | The production file to mutate |
| `mutation` | yes | Exactly what to change, precisely enough that two people would make the same edit |
| `command` | yes | The test command to run under the mutation |
| `expect` | yes | Always `named-tests-fail` |
| `tests` | yes | Which tests must fail. At least one. A mutation that makes *some* test fail somewhere proves less than one that makes the intended test fail |
| `restore` | yes | How to put the file back |

### One check per asserted claim

**Every claim in a `unit-tests` or `test-repair` item's `claims` list is named by at least
one mutation check on that item, or by exactly one waiver — never both.** The linter
enforces it as `claim-without-mutation`.

The rule this replaced asked a `test-repair` item to carry a mutation check *somewhere*.
That was satisfied by one check on an item asserting a dozen claims, which verifies one of
them and says nothing about the other eleven. The obligation belongs to the claim, because
the claim is the thing being verified — which is also why `claim` is a required field.
Without it the linter looking at an item with twelve claims and three checks cannot tell
which three are covered.

**Generating these is more mechanical than it sounds.** A well-formed claim nearly dictates
its own mutation:

| The claim says | The mutation is |
|---|---|
| the query is scoped to the calling user | delete the filter |
| a missing value falls back to the default | change the default to something else |
| the list comes back sorted by date | remove the sort |
| invalid input raises a named error | delete the validation branch |
| the total includes tax | drop the tax term |

If you cannot see the edit, that is usually the claim being vague rather than the claim
being unmutatable. Sharpen the claim first; a claim you cannot falsify is a claim you cannot
write a test for either.

**The removal exemption is untouched.** An item carrying no claims — a repair that deletes
tests rather than strengthening them — has nothing to cover, and its `pattern-count`
expecting zero or `file-exists` marked absent remains what verifies it.

### The waiver, for a claim that genuinely admits no edit

```yaml
mutation-waiver:
  - claim: C18
    reason: "The claim is that the module exports exactly these four names. No edit to the
             module body falsifies it; deleting an export changes the module's shape rather
             than its behavior, and the file-exists check already covers that."
```

| Field | Required | Meaning |
|---|---|---|
| `claim` | yes | Which claim is waived. Must be one the item asserts |
| `reason` | yes | Why this claim admits no small named falsifying edit. At least forty characters |

**Held to the same standard as the guard waiver: a waiver whose reason is convenience
rather than impossibility is a violation of the requirement, not a permitted shortcut.**
"Hard to mutate", "the test is indirect", and "covered by the other checks" are all
statements that the work is inconvenient. The bar is that no small named edit exists, and
the owner reads every waiver at the review gate.

The forty-character floor is deliberate and is not the real check. It exists because "N/A",
"not applicable", and "none" are the shapes a waiver takes when it is being used to get past
the linter, and none of them survives it. A determined planner can still write forty
characters of nothing; the owner is what catches that.

**Why the waiver exists at all.** Without it, a planner facing a genuinely unmutatable claim
has two moves — invent a check that does not falsify the claim, or drop the claim — and both
are worse than a recorded, reviewable admission that this one claim is verified structurally
rather than by mutation. The waiver is what lets the obligation be absolute.

### The protocol, which is not optional

This is the only check that modifies production code, and it is permitted only under the
procedure the assessment skill already uses:

```bash
# 1. Back up outside the repository
cp <target> "$SCRATCH/target.backup"

# 2. Make the minimal mutation

# 3. Run only the tests that claim to cover it
<command>

# 4. Restore unconditionally and verify TWO ways
git checkout -- <target>
git status --porcelain <target>          # must be empty
diff -q "$SCRATCH/target.backup" <target>  # must be identical
```

Both verifications are required. A `git status` that is clean proves the file matches the
index; the `diff` proves it matches what was there before anything was touched. Restore
runs whether the test failed, passed, or the run crashed.

**Never delegate a mutation check to a subagent.** Whoever makes the change controls the
restore, in the same process, or the repository can be left modified by a failure the
delegating side never sees.

Use this check where the item's purpose is assertion strength: adding filter assertions,
adding write-payload assertions, replacing an identity stub with the real helper. For
`sbcf-app` it is the only check type that verifies what the plan is for.

---

## 5. `pattern-count`

A pattern occurs a stated number of times across a stated scope.

```yaml
- kind: pattern-count
  scope:
    - "__tests__/competition-discovery.test.tsx"
  pattern: "expect\\(true\\)\\.toBe\\(true\\)"
  expect: 0
```

| Field | Required | Meaning |
|---|---|---|
| `scope` | yes | Files or globs, repository-relative. At least one |
| `pattern` | yes | A regular expression |
| `expect` | yes | The exact count required afterwards |
| `comparison` | no | `exactly` (default), `at-least`, or `at-most` |

Use it for completion that means absence — placeholders removed, a deprecated helper gone,
every one of eight files carrying the shared mock. Do not use it as a proxy for quality: a
count of `expect(` calls says nothing about whether they assert anything, and a check that
looks rigorous while measuring nothing is exactly the failure this whole suite exists to
expose.

---

## Choosing checks for an item

| Item type | Checks it normally carries |
|---|---|
| `infrastructure` | `tests-pass` on an empty run, `file-exists` on the coverage output |
| `characterization` | `file-exists`, `tests-pass` |
| `seam` | `guard-holds`, plus `tests-pass` for the existing suite |
| `unit-tests` | `file-exists`, `tests-pass`, plus a `coverage-delta` field |
| `test-repair` | `tests-pass`, and **`mutation` whenever the repair's purpose is assertion strength** |

The linter enforces two of these: a `seam` item with a `guarded-by` must carry a
`guard-holds` check naming that item, and a `test-repair` item must carry either a
`mutation` check or a `justification` saying why the repair's effect is visible some other
way.

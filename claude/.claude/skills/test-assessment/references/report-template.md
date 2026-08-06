# Report Template

The section order below is fixed by requirement R-7.2. Do not reorder it. Omit a section
only when it does not apply, and when you omit one, say why in Degradations rather than
letting it vanish silently.

Replace every angle-bracket placeholder. A placeholder left in the output is a defect.

**Labels used throughout.** `[measured]` for a number a tool produced, `[cited: doc §n]`
for a claim traced to a document, `[inferred]` for a claim read from code, and
`[contested]` for a claim the verification pass could not settle. Every statement of
intended behavior carries one.

---

````markdown
# Test Suite Assessment: <repository name>

Generated <date> by the `test-assessment` skill (stage one of four).
Mode: **<requirements-informed | requirements-informed in part | inference>**.
Verification: **<passed | passed with corrections | skipped — lower confidence>**.

<**"Requirements-informed in part" is mixed mode and is a legal declaration**, not a
failure to decide. Use it when some documents state this code's behavior and others do
not. It corresponds to `requirements-informed-partial` in the index. When you declare it,
Section 6 must name which documents ground which parts of the map, and the caveat below
applies to the inferred portion.>

> **Standing caveat (inference mode, and the inferred portion of mixed mode).** <No / Not
> all> intended behavior could be traced to requirements or specification material, so
> <all / the rest> of it is inferred from the code itself. Inference cannot distinguish a
> bug from a feature: a behavior described below as inferred may be describing a defect.

## 1. Executive summary

<Three to six sentences. What state the suite is in, what the central problem is, and
what it would actually take to get to a suite the owner can trust. Lead with the finding,
not the process.>

### Risk-ranked findings

| ID | # | Finding | Risk | Basis |
|---|---|---|---|---|
| F1 | 1 | <finding> | High | <complexity, churn, verification status> |
| F2 | 2 | <finding> | High | <…> |
| F3 | 3 | <finding> | Medium | <…> |

<**The ID column is the interface to stage two and is not decorative.** Identifiers are
assigned in presentation order on first draft and never renumbered afterwards. The `#`
column is the rank and may change when a correction reorders the ranking; the `ID` column
may not. `references/index-schema.md` states the rules for both, including what to do when
a correction splits or removes a finding.>

<**Mark a contested finding in this table** by appending `[contested]` to its finding text,
so a reader of the summary sees it without reaching Section 10.>

**Ranking method.** <State it explicitly so a reader can disagree. Name the inputs —
cyclomatic complexity, change frequency from version control, presence of meaningful
verification — how they combine, and any input that was unavailable.>

### The realistic path to a trustworthy suite

<**A classification, not a plan.** Say which of the three it is and why: unit tests written
directly against code that is already testable; seam refactorings first, because too much
code is unreachable; or integration-style tests, because the architecture does not admit
unit tests at reasonable cost. Justify it with the proportions from Section 8.

**Do not write an ordered list of steps.** Requirement R-6.7.2 asks stage one to classify
the path; sequencing it is stage two's job, and a numbered list here anchors the planner to
an ordering produced without the planning stage's analysis. Stage one states what is true;
stage two decides what order to act in.>

**Dependencies between findings** <— state these as facts, because the planner needs them
and cannot derive them from the code alone. They constrain any sequence without prescribing
one. Examples of the shape: "R2's characterization test cannot be written until a fixture
directory exists, so R2 is unsafe to execute first"; "R3 has no prerequisite and is
independent of the others"; "setting `collectCoverageFrom` will fail the existing global
threshold, so the two changes must land together." If there are no such dependencies, say
so — that is itself useful.

**Give every endpoint an identifier.** A dependency whose other end is free text — "the
threshold decision", "whatever the team decides about fixtures" — is one the planner cannot
resolve. When an endpoint is a question rather than a finding or a recommendation, give it
a `Q`-number and list it under Open questions below, so the edge has two identifiers.>

**Open questions** <— questions this assessment identified and deliberately did not answer,
because answering them means weighing risk, scope, or intent. Each gets a `Q`-number, states
which findings or recommendations raise it, and says why stage one did not answer it.
Step 7c of the procedure is where these are gathered, and it lists the shapes worth looking
for.

This is not a place to defer work. A question stage one *can* settle from the evidence gets
settled in the prose. This list is for the ones that are genuinely the owner's to decide.

They also give the dependency statements above stable endpoints, but that is a consequence
rather than the purpose — most open questions are not the endpoint of any dependency.

| ID | Question | Raised by | Why stage one did not answer it |
|---|---|---|---|
| Q1 | <…> | <R2> | <…> |

If there are none, say "None.">

## 2. Measurement provenance and suite health

**Commands run**

```
<exact commands, verbatim, in order>
```

**Tooling**

| Item | Value | How determined |
|---|---|---|
| Language(s) | <…> | <read from manifest / inferred> |
| Test framework | <…> | <…> |
| Test command | <…> | <read from package.json scripts.test / guessed> |
| Coverage tool | <name and version> | <…> |
| Coverage config | <in effect> | <…> |
| Package manager | <…> | <lockfile> |

<Mark every guess as a guess. R-5.1 requires it.>

**Suite health.** <One of: no suite exists; suite exists but does not run, with the
diagnosis and the quoted error; suite runs with N of M failing; suite exceeded the
<n>-second budget and was stopped; suite runs clean.>

<If tests fail: list them, and state explicitly whether the coverage numbers below
include or exclude the failing tests.>

**Test counts**

| Kind | Files | Tests |
|---|---|---|
| Unit | <n> | <n> |
| Integration | <n> | <n> |
| End-to-end (Playwright/Cypress) | <n> | <n> |
| Skipped / disabled / expected-failure | <n> | <n> |

<End-to-end tests are counted separately and never substitute for unit coverage.>

## 3. Coverage

<Omit this section entirely if no suite runs. Do not print zeros that look like
measurements.>

**Overall** — line <n>% `[measured]`, branch <n>% `[measured]`.

| File | Lines | Branches | Uncovered regions |
|---|---|---|---|
| <path> | <n>% | <n>% | <lines> |

<Function-level detail for the files in the top risk tier.>

## 4. Exclusions and effective coverage

| ID | Path or pattern | Category | Reason | Statements |
|---|---|---|---|---|
| X1 | <…> | <A–F> | <…> | <n> |

> Raw coverage <n>% of <n> statements. Effective coverage <n>% of <n> statements after
> excluding <n> statements across <n> files.

**Belongs in tool configuration.** <Which exclusions should move into `[tool.coverage.run]
omit`, `coverage.exclude`, or `coveragePathIgnorePatterns`, so a later stage reproduces
this number.>

## 5. Test quality

<Omit if no tests exist, and say so here in one line rather than deleting the heading.>

**Summary.** <n> tests read (all of them — no sampling). <n> verify behavior. <n> are
weak, broken down below.

| Test | Category | Evidence | What it would take to verify behavior |
|---|---|---|---|
| `<file>:<line>` | <1–4> | `<quoted line>` | <one sentence> |

**Disabled, skipped, and expected-failure tests**

| Test | Marker | Stated reason |
|---|---|---|
| `<file>:<line>` | <…> | <reason, or "reason not stated"> |

<A committed `.only` goes in the top risk tier regardless of anything else, because it
silently disables every other test in its file while the suite reports green.>

**Covered but not meaningfully verified**

<Production code that coverage counts as covered but no test actually checks. This is a
distinct category from uncovered code and often more urgent, because it is actively
misleading. List the code and the weak test responsible.>

| Code | Reached by | Why the verification is not real |
|---|---|---|
| `<file>:<lines>` | `<test>` | <…> |

**Mutation testing.** <Ran with <tool>, <n> mutants, <n> survived — listed below. Or:
not run, because <no suite / tooling unavailable / outside time budget / too few tests
for the result to mean anything>.>

## 6. Behavioral map

Mode: **<requirements-informed | requirements-informed in part | inference>**. <In
requirements-informed mode, name the documents. In inference mode, repeat that every
intended-behavior claim is an inference. In mixed mode, do both, and say which parts of
the map each usable document grounds — that naming is what makes the mixed declaration
checkable rather than a hedge.>

**Documents found**

| Document | Used | Grounds which part of the map | Why not (if unused) |
|---|---|---|---|
| <path> | yes/no | <the modules or behaviors this document states, or "—"> | <…> |

<The third column is what mixed mode requires. In single-mode reports it is either uniform
or empty, which is itself the honest answer.>

<**Per-claim source labeling is mandatory in every mode, including this one.** The mode
label is a summary; `[cited: doc §n]` and `[inferred]` on each statement are the record. A
reader must be able to tell which is which without trusting the summary, and that is the
only reason mixed mode is permitted at all.>

**Map granularity — choose by risk tier, not by uniform rule.**

A per-function table for every module does not survive a large repository: at two thousand
functions it produces a document nobody reads and buries the findings that matter. Scale
the detail to the risk ranking:

| Risk tier | Granularity |
|---|---|
| Top | Full per-function table — intended behavior, source label, where branching and error handling concentrate |
| High | Per-function table for the public interface only; internal helpers summarized in a sentence |
| Medium | Module-level paragraph: responsibility, rough shape, the one or two functions worth naming |
| Low | One line per module in a single summary table, or grouped by directory |

**Granularity applied — state this as a table, not a sentence.** The rule above is the
default; what a reader needs is what you actually did, per tier, in this report. A missing
per-function table is otherwise indistinguishable from an oversight, which is exactly the
confusion this table removes.

| Risk tier | Modules | Granularity used | Why, if it differs from the rule |
|---|---|---|---|
| Top | <n> | Per-function table | — |
| High | <n> | Public interface only | — |
| Medium | <n> | Module paragraph | — |
| Low | <n> | One line each | — |

<Deviating from the default rule is permitted and must be justified in the last column. A
ninety-function repository can be mapped per-function throughout and should say so; a
repository with several thousand production functions cannot, and attempting it buries the
findings that matter under rows of low-risk detail. As a rough target, keep the behavioral
map under about 40% of the report.>

**Modules**

### `<module path>` — <risk tier>

**Responsibility.** <what it is for> `[cited: <doc> §<n>]` or `[inferred]`

| Public function | Intended behavior | Source | Branching / error handling / state |
|---|---|---|---|
| `<name>` | <…> | `[cited/inferred]` | <where complexity concentrates> |

<Repeat per module at the granularity its tier calls for. Note where branching, error
handling, and state manipulation concentrate — these drive both the risk ranking and the
seam recommendations.>

## 7. Traceability

<Omit entirely in inference mode; there is nothing to trace to.>

| Requirement | Implementing code | Verifying test | Status |
|---|---|---|---|
| <doc §n> | <path> | <test or none> | verified / implemented but untested / **not implemented** |

**Requirements with no matching test.** <Listed separately from uncovered code. A
requirement with no implementing code at all is invisible to coverage tooling — coverage
cannot report on code that does not exist — which is why this list matters independently
of Section 3.>

## 8. Testability classification

| Category | Functions | Share |
|---|---|---|
| Testable as it stands | <n> | <n>% |
| Export only | <n> | <n>% |
| Requires a seam | <n> | <n>% |
| Reachable only by integration-style tests | <n> | <n>% |
| Excluded (Section 4) | <n> | — |

<**This table is machine-checked against the index's `testability` entries.**
`check_index.py` recomputes every count and share from them and fails the report on a
mismatch, so write the table from the entries rather than from an earlier draft. The row
labels above map onto the five index categories; you may split a row to name two different
reasons for a seam, and the rows sum into the one category.

Shares are of the classified functions **excluding** the excluded ones, which is why that
row carries an em dash rather than a percentage. State the unit of measurement — functions,
from the complexity analyser's enumeration — and be consistent with it.>

**Scope of the classification.** <Which risk tiers were classified exhaustively, which
recommendation locations were pulled in regardless of tier, and whether this is the whole
function inventory or a bounded subset of it. Must agree with `testability_scope` in the
index.

The standard rule, unless you say otherwise: every function in the top and high tiers, plus
every function named in any recommendation's locations. A repository small enough to
classify exhaustively should be, and should say so.

This paragraph is what tells the planning stage whether a claim it cannot resolve is a
mistake or a backfill request. Without it, both look the same.>

**What the proportions mean.** <The judgment. This is what the classification is for.
Tie it back to the path stated in Section 1.>

**Why code needs a seam here** — <the concrete reasons found in this repository: direct
database, network, filesystem, or clock access; internally constructed dependencies; real
work in constructors. Give counts.>

## 9. Seam recommendations with paired characterization tests

<Each recommendation draws from the closed four-seam catalog. If no catalog seam fits a
piece of code, that is stated rather than a fifth seam type being invented.

**Not every recommendation is a seam.** A repository whose problem is assertion quality or
measurement scope gets recommendations that change test code or configuration, which this
stage is permitted to make. Those still get `R`-numbers and still appear in the index, with
their `kind` field distinguishing them from seams. The seam catalog is closed for seams; it
does not limit what a recommendation may be about.

**The `R`-number is the stable identifier** stage two references, under the same
no-renumbering rule as findings.>

### R1 — <short title>

| | |
|---|---|
| **Seam type** | <1 Extract pure function / 2 Pass dependency in / 3 Wrap clock, filesystem, network / 4 Move work out of constructor> |
| **Location** | `<file>:<lines>` |
| **Becomes testable** | <the specific behavior> |
| **Size** | <small / medium / large, with a sentence on why> |
| **Why this seam** | <only when the choice among catalog seams was not obvious> |

**Characterization test to write first**

- **Boundary**: <the outermost point already reachable without changing anything>
- **Inputs**: <specific values, including at least one error or edge case>
- **Observes**: <return value, output written, calls made outward, rendered result>
- **Known imprecision**: <time, randomness, ordering — how it is pinned down, or what
  remains uncontrolled>

<Repeat per recommendation. Characterization tests are scaffolding to guard the
refactoring, not part of the final suite; they are removed once real unit tests cover the
behavior.>

<If a characterization test cannot be written for a seam because the code has no reachable
boundary, say so — that seam is not safe to execute, and that is a top-tier finding.>

## 10. Verification pass

**Status.** <Ran with a fresh-context agent | Skipped because <reason> — this report is
lower confidence.>

**Verified in full.** <the top risk tier — list what was checked>
**Sampled.** <what portion of the remainder, and how it was selected>

| Claim checked | Verdict | Resolution |
|---|---|---|
| <…> | confirmed / corrected / contested | <what the evidence showed> |

**Corrections applied.** <What the verifier found wrong and what the report now says.
Corrections were resolved by returning to the code, test, or document — never by
averaging the two positions.>

**Contested findings.** <Claims where the evidence is genuinely ambiguous, with both
readings stated. These remain in the report deliberately; a contested finding is useful
input to the planning stage.>

## 11. Degradations

<Every reduction in scope or confidence that applied. If none applied, say "None." Do not
omit the section.>

| ID | Degradation | Effect on this report |
|---|---|---|
| D1 | <e.g. No version control history> | <Risk ranking used two of three inputs> |

## 12. Reproducing this measurement

<**Emit paths relative to the repository root, never absolute paths.** A block containing
an absolute home-directory path — one rooted at the `Users` or `home` directory and naming
an account — is not reproducible by anyone else, on another machine, or by a later agent
working in a different checkout, which defeats the section's purpose. Use a variable for
the skill location and `.` for the repository.

`check_index.py` enforces this across every fenced block in the report, not only this one,
and reports it as `absolute-path`.>

```
SKILL=<path to the test-assessment skill>/scripts   # set this to wherever the skill lives
# Run from the repository root.

python3 $SKILL/detect_env.py  --repo . --json > /tmp/env.json
python3 $SKILL/complexity.py  --repo . --json > /tmp/cx.json
python3 $SKILL/census.py      --repo . --json > /tmp/census.json
python3 $SKILL/churn.py       --repo . --json > /tmp/ch.json
<test + coverage command, exactly as run, with coverage written outside the repository>
python3 $SKILL/parse_coverage.py <coverage file> --json > /tmp/cov.json
python3 $SKILL/rank.py --repo . --complexity /tmp/cx.json --churn /tmp/ch.json \
                       --coverage /tmp/cov.json --json > /tmp/rank.json

# Every figure in this report comes from the consolidator, which reads all of the above.
# Re-running any analyser above means re-running this and re-checking the prose.
python3 $SKILL/figures.py --repo . --report docs/test-assessment.md \
                          --complexity /tmp/cx.json --env /tmp/env.json \
                          --census /tmp/census.json --churn /tmp/ch.json \
                          --coverage /tmp/cov.json --json > /tmp/figures.json
```

Recorded at commit `<sha>`. Tool versions: `<runner, coverage tool, parser>`.

Coverage numbers are not comparable across configurations. A later stage that changes the
coverage configuration must re-baseline rather than compare against the numbers above.

## 13. Reconciliation with the run ledger

<**Omit this section entirely when the repository has no `docs/test-ledger.json`.** A first
assessment has nothing to reconcile, and an empty section would be ceremony. When the section
is absent, section 14 below is renumbered to 13.

When a run ledger does exist, R-7.2 of the reporting requirements binds this report: every item
the ledger holds open is explicitly **confirmed** (still true), **updated** (changed, with
evidence), or **contested** (wrong or no longer meaningful, with evidence). An open item this
report simply does not mention is a lint failure, because silence and resolution look identical
from the outside — which is the whole reason the rule exists.

List what is open first, from `ledger.py --open`, then one subsection per item.>

The run ledger at `docs/test-ledger.json` holds <n> open item(s) as of run `<run_id>`, closed
`<date>`. <m> commit(s) have landed since.

| Item | Kind | Open since | Disposition |
|---|---|---|---|
| DF-1 | defect | 2026-08-04-a1b2c3d | confirmed |
| PF-03 | pipeline-finding | 2026-08-04-a1b2c3d | contested |

### DF-1 — <one line, the ledger's summary>

<Disposition, then the evidence for it. All three dispositions carry evidence and `confirmed`
needs it most rather than least: it is the disposition that costs nothing to write and asserts
the most — that somebody looked and the item is still true. Name what you looked at.>

<Repeat per open item. The same dispositions and the same evidence go into the index's
`reconciliation` array below, which is what `check_index.py --ledger` reads.>

---

## 14. Machine-readable index

<This section is the interface to stage two, and it is section 13 rather than 14 in a report
with no reconciliation section above it. It carries the identifiers, classifications,
and numbers the planning stage needs, and nothing the prose above does not already state.

**Write it last, after the verification pass has applied its corrections.** An index written
before verification describes a report that no longer exists.

Every field is specified normatively in `references/index-schema.md`. Validate the block
with `scripts/check_index.py` before finishing; it parses the JSON, checks every identifier
and enumeration, and cross-checks each identifier against the prose above.

Emit exactly one block, with the info string exactly `json assessment-index`.

When section 13 above exists, this block carries a `reconciliation` array holding the same
dispositions and the same evidence, one entry per open ledger item. When it does not, omit the
array — a repository with no run ledger has nothing to reconcile.>

```json assessment-index
{
  "index_version": "1.2",
  "repository": "<name>",
  "report_path": "docs/test-assessment.md",
  "generated": "<YYYY-MM-DD>",
  "commit": "<sha or null>",
  "mode": "<requirements-informed | requirements-informed-partial | inference>",
  "verification": "<passed | passed-with-corrections | skipped>",
  "findings": [],
  "recommendations": [],
  "exclusions": [],
  "degradations": [],
  "open_questions": [],
  "dependencies": [],
  "coverage_baseline": {},
  "metrics": [],
  "testability": [],
  "testability_scope": {
    "tiers": ["top", "high"],
    "recommendation_locations": [],
    "map_granularity": {
      "top": "per-function",
      "high": "public-interface",
      "medium": "module-summary",
      "low": "one-line"
    },
    "complete": false,
    "classified_functions": 0,
    "total_functions": null,
    "note": "<the scope rule in one sentence>"
  }
}
```
````

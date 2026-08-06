---
name: test-assessment
description: Assess a repository's test coverage, test quality, and testability, then write a durable Markdown report at docs/test-assessment.md. Use when asked to assess or audit test coverage, judge whether a test suite can be trusted, find out why coverage is low, or work out how to start testing a codebase that has few or no tests. Read-only with respect to source and test code — it recommends changes, it never makes them.
---

# Test Suite Assessment

Stage one of a four-stage test improvement workflow. This stage assesses. It does not
plan, write tests, or refactor.

The primary target is a repository with few or no tests. In that case the coverage
percentage is a foregone conclusion and is not the valuable output. The valuable outputs
are a behavioral map of the production code, a testability classification, and an honest
account of what a trustworthy suite would actually require.

## Absolute rules

1. **Read-only.** Never modify, create, or delete production code or test code in the
   target repository. The only file you may write is the report itself. You may run the
   existing test suite and coverage tooling. If a coverage tool wants to write config
   into the repo, do not let it — pass configuration on the command line instead.
2. **Never fabricate.** If you cannot determine something — the test command, the intent
   of a function, why a test is skipped — say so in the report. Do not guess silently.
3. **Every claim carries its basis.** A measurement, a cited document, a specific file
   and line, or an explicit inference label. Never present an inference with the
   confidence of a measurement.
4. **Degrade, do not fail.** A missing suite, a broken suite, absent requirements, or
   unavailable tooling each reduce the report's scope. Record exactly which reductions
   applied in the Degradations section. Never abort the assessment.
5. **Do not sample the tests.** Read every existing test file in full. Target repos have
   few tests; exhaustive reading is affordable and is required.

## Ecosystems supported in this version

Python with pytest, and TypeScript or JavaScript with Vitest or Jest. Read
`references/ecosystems.md` for detection rules, commands, and coverage formats.

For any other language, still produce the report — the behavioral map, exclusions,
testability classification, and seam recommendations are language-independent judgment
work. Only the measured parts (coverage numbers, cyclomatic complexity) degrade, and the
Degradations section must say so.

## Inputs

All optional. The skill runs with no arguments against the current working directory.

| Option | Meaning | Default |
|---|---|---|
| `--requirements <path>...` | Requirements or specification documents to use | auto-discover |
| `--test-command "<cmd>"` | Command that runs the tests | auto-detect |
| `--exclude <glob>...` | Directories to leave out of analysis | see exclusion catalog |
| `--output <path>` | Where the report is written | `docs/test-assessment.md` |
| `--time-budget <seconds>` | Cap on suite execution | `600` |
| `--no-verify` | Skip the verification pass | verification runs |
| `--backfill-index` | Add the machine-readable index to an existing report and stop | full assessment runs |

If the user gave hints in prose rather than flags, use them the same way.

## Procedure

Work through these steps in order. Each writes findings you will assemble in Step 8.

### Step 1 — Discover requirements material

Search the repository for material that states intended behavior: files under `docs/`,
`spec/`, `specs/`, `requirements/`, `adr/`, `rfc/`, or `design/`; files whose names
contain `requirement`, `spec`, `design`, `architecture`, `prd`, or `adr`; and the README,
`CLAUDE.md`, and `AGENTS.md`.

**Judge each document by whether it states intended behavior of *this* code**, not by its
filename. This distinction decides the mode and it is routinely got wrong. A file named
`requirements.md` may turn out to list installation prerequisites. A user guide may
describe the workflow of a product the code merely *exports*, not the code's own behavior.
Read enough of each to tell.

This decides the report's **mode**, which changes its confidence throughout:

- **Requirements-informed mode** — usable behavioral material was found and covers most of
  what the code does. Statements of intended behavior cite a document and a section.
- **Mixed mode** — some documents state behavior and others do not, so part of the map is
  cited and part is inferred. **This is a legal mode and is often the honest answer.**
  Declare it as "requirements-informed in part", name exactly which documents were usable
  and which were not and why, and carry the inference caveat for the inferred portion. It
  is permitted *only* because per-claim labeling is mandatory: every statement still
  carries `[cited: doc §n]` or `[inferred]`, so a reader can tell which is which without
  trusting the mode label. Never use mixed mode as a way to avoid deciding about a
  document — each one is either usable or not, and the report says which.
- **Inference mode** — nothing usable was found. Intended behavior is inferred from
  code, names, docstrings, error messages, public interfaces, and the README, and every
  such statement is labeled as an inference.

In inference mode, and for the inferred portion of mixed mode, the report must carry this
standing caveat near the top: *inference cannot distinguish a bug from a feature, so a
behavior read from the code may be describing a defect.*

List every document you found and whether you used it, **with a reason when you did not**.
Do not stop when you find none.

### Step 2 — Detect the environment

Run the detection script:

```bash
python3 <skill>/scripts/detect_env.py --repo . --json
```

It reports languages, package manifests, test frameworks, candidate test commands,
coverage configuration, and — importantly — which test directories are end-to-end
(Playwright, Cypress) rather than unit tests.

**End-to-end tests are not unit tests.** A repository with a large Playwright suite and
no unit tests looks tested from the outside and is not. Count and report them separately,
and never let them stand in for unit coverage.

Confirm the script's findings by reading the manifests yourself. Anything the script
inferred rather than read directly must be recorded in the report as a guess, per R-5.1.

### Step 3 — Run the suite and measure coverage

Read `references/ecosystems.md` for the exact commands.

Impose the time budget (default 600 seconds) on suite execution. Then branch:

- **No test suite exists.** Skip execution. State that plainly. Go to Step 5. There are
  no coverage numbers, and the report must not imply otherwise.
- **Suite exists but does not run.** Diagnose as far as you can — missing dependencies,
  a config error, an import failure. State that the suite is broken and quote the error.
  Report no numbers built on a failed run. Go to Step 4 (you can still read the tests).
- **Suite runs, some tests fail.** Report the failures as a finding. State explicitly
  whether the coverage numbers include or exclude the failing tests. Continue.
- **Suite exceeds the time budget.** Stop it. Report that it was stopped and at what
  point. Continue with whatever partial data exists.
- **Suite runs clean.** Produce line coverage, and branch coverage where the tooling
  supports it, at file and function granularity.

Parse the coverage output with:

```bash
python3 <skill>/scripts/parse_coverage.py <coverage-file> --json
```

Record **measurement provenance** — the exact commands you ran, the coverage tool and its
version, and the configuration in effect. Coverage numbers are not comparable across
configurations, and the later planning stage must be able to reproduce this measurement.

### Step 4 — Inventory and judge the existing tests

Read every test file in full. For each test, decide whether it verifies behavior or
merely executes code.

**Measure the suite before deciding how to read it.**

```bash
find <test-dirs> -name "*.test.*" -o -name "test_*.py" -o -name "*_test.py" | xargs wc -l | tail -1
```

- **Under ~6,000 lines** — read them yourself, sequentially. Fan-out costs more than it saves.
- **Over ~6,000 lines** — fan out across parallel readers, per the procedure below.

Rule 5 forbids sampling, and that rule holds at every size. Fan-out is how it is honoured on
a large suite, not an exception to it: every test still gets read in full, just not all by
one reader. Do not silently switch to sampling because a suite is large. If for some reason
you cannot read everything, say so explicitly in the report and state exactly what was left
out — a stated gap is a finding, a hidden one is a defect.

**Fan-out procedure.** Full prompt template and merge rules in
`references/parallel-reading.md`. In brief:

1. Partition test files into 5–7 groups balanced by **line count**, using longest-first bin
   packing, so each reader gets roughly 3,000–4,000 lines. Balance by lines, not file count —
   one 3,000-line file outweighs six 300-line ones.
2. Spawn one `general-purpose` agent per group **in a single message** so they run
   concurrently. Give each the same rubric verbatim, its own disjoint file list, and an
   explicit read-only instruction.
3. Require a **quoted line of code for every classification**. This is what makes the merge
   tractable and the results checkable; a judgment without a quote is unusable.
4. Ask each reader for the strongest tests it saw, not only the weak ones. Without this the
   merged report has no calibration and reads as uniformly damning.
5. **Cross-check the merge**: compare the readers' total test-case count against the count
   the test runner reported. A delta under about 1% indicates the reading was complete. A
   large delta means files were missed — find out which before writing anything.
6. Treat **convergence as evidence**. When several readers independently report the same
   structural problem in different files, that is far stronger than one reader's opinion, and
   the report should say that it was independently reached.
7. Spot-check the sharpest claims yourself against the source before writing them down.
   Readers are usually right and occasionally not.

Classify weak tests using the rubric in `references/test-quality-rubric.md`, which covers
assertion-free tests, mock-asserting tests, implementation-restating tests, and
unreviewed snapshot tests. Quote the specific lines that justify each classification.

Identify every disabled, skipped, or expected-failure test — `@pytest.mark.skip`,
`@pytest.mark.xfail`, `it.skip`, `describe.skip`, `it.todo`, `test.failing`, commented-out
tests. Report them as silent subtractions from real coverage, with the reason for each
skip if it is stated and "reason not stated" if it is not.

Produce the **covered-but-unverified** category: code that coverage counts as covered but
that no test meaningfully checks. This is a distinct category from uncovered code, and it
is the reason the raw coverage number alone is insufficient.

**Optional mutation testing.** Only if all of these hold: a nontrivial runnable suite
exists, mature mutation tooling is available for the ecosystem (`mutmut` or `cosmic-ray`
for Python, `stryker` for TypeScript), and the time budget allows it. Skip it when there
are few or no tests — it measures nothing there. The report must state whether mutation
testing ran, and if it did not, why not.

### Step 5 — Build the behavioral map

Inventory the production code: modules and their responsibilities, public functions and
what each is supposed to do, and where branching, error handling, and state manipulation
concentrate.

Every statement of intended behavior carries its source — a cited document in
requirements-informed mode, an explicit `[inferred]` label in inference mode.

**Scale the map's granularity to the risk tier** — full per-function tables for the top
tier, public interface only for high, a module-level paragraph for medium, one line each
for low. `references/report-template.md` gives the rule. A uniform per-function table does
not survive a large repository, and burying top-tier findings under a thousand rows of
low-risk detail defeats the report.

**Record what you actually did in the granularity table**, per tier, rather than asserting
that you followed the rule. Deviating is allowed and must carry its reason in that table. A
ninety-function repository can be mapped per-function throughout; a repository with several
thousand cannot. Without the table, a missing per-function table reads as an oversight
rather than a decision, and Step 6's testability classification inherits the same tier
boundary, so the two sections must agree about where it falls.

Where requirements exist, do a rough **traceability pass**: map each requirement to the
tests that plausibly verify it. Requirements with no matching test are a separate finding
from uncovered code, because a behavior with no implementing code at all is invisible to
coverage tooling.

### Step 6 — Exclusions and testability

**Exclusions.** Identify code that does not warrant unit testing using
`references/exclusion-catalog.md` — generated code, vendored dependencies, framework
boilerplate, migrations, trivial accessors, dead code. List each exclusion with its
reason. Report **effective coverage** (coverage of what remains) alongside the raw number,
and note which exclusions belong in the coverage tool's own configuration.

**Testability classification.** Classify every area of the behavioral map as either
testable as it stands or requiring a seam first. Code needs a seam when it reaches
directly into a database, the network, the filesystem, or the clock; when it constructs
its own dependencies internally; or when it does real work in a constructor.

State the **proportion** in each category, and state which realistic path to a
trustworthy suite you believe follows from it: unit tests directly, seam refactorings
first, or integration-style tests. That proportion is the whole point of the
classification — say what you think it means.

**Classify at function granularity, over a bounded set.** The proportions above are what a
reader needs; the planning stage needs something else, and cannot run without it. Its
claim-enablement rule resolves each claim's `path:line` to a function and asks whether a
test can reach it. Give it that, one entry per function, in the index's `testability`
section.

*Which functions.* Not all of them — a repository with several thousand production
functions cannot be classified exhaustively, and attempting it contradicts Step 5's
granularity rule. The set is:

- every function in the **top** and **high** risk tiers, and
- every function named in **any recommendation's locations**, whatever tier it sits in.

Classify a small repository exhaustively where you can. Ninety functions is
exhaustible; three thousand is not. Record which you did in `testability_scope`, and set
`complete` to `true` only when the set really is every function in the repository — that
flag is what tells the planner whether an unresolvable claim is a planning error or a
backfill request.

*Take the enumeration from the analyser, never from reading.* `complexity.py` emits `name`,
`line`, and `end_line` for every function it finds. Copy those three fields. A hand-written
line range that is off by two does not fail loudly; it silently stops resolving, and the
planner then asks you to backfill a function you already classified.

Functions sit under `files[].functions[]`, each with `name`, `line`, `end_line`, and
`complexity`:

```bash
python3 <skill>/scripts/complexity.py --repo . --json > /tmp/cx.json
python3 -c "
import json
for entry in json.load(open('/tmp/cx.json'))['files']:
    for fn in entry['functions']:
        print(f\"{entry['path']}:{fn['line']}-{fn['end_line']} {fn['name']} cx={fn['complexity']}\")
"
```

Check `counts_are_exact` in the same output before you rely on the enumeration. When it is
`false` the token scanner ran and undercounts functions roughly threefold, so the classified
set is incomplete in a way the scanner cannot tell you about. Record that as a degradation,
say so in `testability_scope.note`, and keep `complete` false.

*The five categories, closed:*

| Category | Use when |
|---|---|
| `testable-as-is` | A test can reach and drive it today |
| `export-only` | Already pure, already separated; only the missing `export` keeps a test out |
| `needs-seam` | A catalog seam must land first. Name the seam type (1–4) and the recommendation |
| `integration-only` | No catalog seam fits. This is a legitimate finding, not a failure to classify |
| `excluded` | Section 4 excludes it. The file must fall under some exclusion's paths |

**Check `export-only` before you reach for `needs-seam`.** A function that is already pure
and already at the top level, and merely unexported, needs one keyword rather than a
refactoring. Recommending the full extraction there asks for behavior-changing work that
buys nothing. `references/seam-catalog.md` states the minimal form and where it stops
sufficing.

**`integration-only` is where the closed seam catalog leaves code, and that is correct.**
When no catalog seam fits, say so rather than inventing a fifth seam type. Do not force
such a function into `needs-seam` to make the table tidier — the planner reads that as
"reachable once a seam lands", and no seam is coming.

*State the proportions in prose.* The per-function entries are a machine interface and the
index is otherwise forbidden from carrying anything the prose does not state. The exception
is paid for by a cross-check: `check_index.py` recomputes each category's count and share
from the entries and fails the report when Section 8's table disagrees. Write the table
from the entries, not from an earlier draft.

**Classify the path; do not sequence it.** R-6.7.2 asks which of the three paths is
realistic, and answering that is required. Writing an ordered list of steps is not: it
crosses into stage two's work and anchors the planner to an ordering derived without the
planning stage's analysis. Stage one establishes what is true; stage two decides what order
to act in.

What stage one *should* supply instead, because the planner cannot derive it from the code
alone, is the **dependencies between findings** — which recommendations are prerequisites
for others, which are independent, and which must land together to avoid breaking the
build. State those as facts. They constrain any sequence without prescribing one. If there
are none, say so.

### Step 7 — Seams, characterization tests, and risk ranking

For code requiring a seam, recommend exactly one from the **closed catalog** in
`references/seam-catalog.md`. Only four seam types are permitted. Recommendations outside
the catalog — new architectures, interface hierarchies, framework adoption, general
redesign — are prohibited. If no catalog seam fits, say so rather than inventing one.

Each recommendation names the seam type, the exact location (file and line), the behavior
that becomes testable once the seam exists, and a size estimate.

Each recommendation is **paired with the characterization test** that must be written
first to guard the refactoring: what boundary it captures behavior at, and for what
inputs. Refactoring untested code is where refactoring is most dangerous, and this
pairing is what makes the recommendation safe to execute in a later stage. A seam
recommendation without its characterization test is incomplete.

**Never count anything by hand.** Call sites, function counts, file counts, occurrences of
a pattern — all of it is deterministic work that R-9.1 assigns to scripts, and every report
that has hand-counted has miscounted. One claimed "20 direct browser API call sites" where
the true figure was 37.

```bash
python3 <skill>/scripts/census.py --repo . --json      # dependency call sites, exact
```

`census.py` strips comments and string literals before matching, which is the specific
thing eyeballing gets wrong, and it reports every location as `path:line`. It covers
browser storage, media queries, the clock, randomness, network, filesystem, DOM, build-time
globs, environment variables, and subprocesses; pass `--pattern name:regex` for anything
else you need counted. Quote its numbers directly.

**Risk ranking.** Rank findings by risk, never by coverage percentage. Compute the
deterministic inputs:

```bash
python3 <skill>/scripts/churn.py --repo . --json
python3 <skill>/scripts/complexity.py --repo . --json
python3 <skill>/scripts/rank.py --repo . --complexity <f> --churn <f> --coverage <f> --json
```

The ranking combines behavioral complexity, change frequency from version control
history, and the presence or absence of meaningful verification. State the ranking method
in the report so a reader can disagree with it. If the repository has no version control
history, the ranking loses one of its three inputs — say so.

### Step 7b — Mandatory label audit before writing

**Do this every time. It is the most common defect in this skill's output — it has occurred
in consecutive reports and vigilance alone does not prevent it.**

**Every number in the report comes from one place.** Run the consolidator, which reads all
the analysers and returns each figure with its basis and the command that produced it:

```bash
python3 <skill>/scripts/figures.py --repo . --report docs/test-assessment.md --json
```

Quote its values. Do not recompute a figure by hand, and do not carry one over from an
earlier draft. Where a figure is not in its output, it is not a figure this skill measured —
say where it came from, or do not state it.

**Re-running any analyser means re-running `figures.py` and re-reading the report for the
old number.** The script records every changed figure as `superseded`, and `check_index.py`
fails the report when a superseded value with three or more digits still appears in the
prose. This is not a hypothetical: one report retained token-scanner figures in its
recommendation prose after an analyser correction had recomputed every figure in its tables,
so the report stated two different function counts and only the tables were right.
Correcting the tables is the half of the job people do.

The rest of this step is the judgment the script cannot do for you. List every number you
intend to put in the report and mark each one `measured` or `estimated`. A number is
**measured** only if a tool that genuinely parses or executes produced it: coverage
percentages and test counts from the test runner, line counts from `wc`, file counts from
the filesystem, commit counts from git.

**`complexity.py` tells you which it produced.** Check the `counts_are_exact` field and
`basis_by_language` in its output. Do not assume:

- `counts_are_exact: true` — the TypeScript compiler parsed the source. Complexity values
  **and function counts** are exact and may be reported as measurements.
- `counts_are_exact: false` — the compiler could not be resolved from the target repository,
  usually because its dependencies are not installed, so the token-scanner fallback ran.
  Then **every** TS/JS complexity value and function count is an estimate, and the scanner
  undercounts functions roughly threefold. Say so wherever the numbers appear.

Python complexity via `ast` is always exact. The distinction is language-specific, so state
which languages any caveat applies to rather than blanketing the report.

Call-site counts from `census.py` are always exact.

Rules that follow:

- Never write "measured" beside an estimated number.
- Function counts and complexity values share one basis. Reports have repeatedly labelled
  the complexity correctly and the counts as "measured"; they come from the same pass.
- Prefer ratios of estimates over absolute estimates when the fallback ran. The same
  undercount applies above and below the line, so a share survives better than a count.
- When an estimate appears in the executive summary or a findings table — the places a reader
  trusts most — carry the qualifier there, not only in an appendix.
- If the fallback ran, say plainly *why* (dependencies not installed) and note that
  installing them would make the figures exact. Do not install them yourself.

### Step 7c — Record the open questions

The second of two mandatory passes before writing. By this point the analysis is done, so you
know what you could not answer.

An **open question** is something this assessment identified and deliberately did not answer,
because answering it means weighing risk, scope, or intent rather than reading evidence. Give
each one a `Q`-number, phrase it as a question, name the findings or recommendations that
raise it, and say why stage one did not answer it.

**The test for whether something belongs here is whether you could settle it by reading.** If
you could, settle it in the prose. This list is not a place to defer work, and a question
parked here that the evidence would have answered is a question you have handed to the owner
instead of doing your job. Stage two escalates every one of these to a person, so a
needlessly parked question costs somebody a decision they should never have been asked for.

**The second test is whether the answer is genuinely open, or only the timing is.** "Should
these components be tested at all?" is not an open question — the answer is yes, eventually,
and everyone knows it. What is actually open is the order and the harness, which is
*sequencing* and belongs in the recommendations with its cost stated. This distinction matters
more than it sounds: a question phrased as *whether* invites stage two to answer "not now",
and a whole area of the repository leaves the plan on the strength of a question that was
never in doubt. That has happened — one report asked whether five components ranked `high`
should be tested, and the plan built on it reached a third of the repository.

So: if you catch yourself writing "should X be tested at all", stop. Write the recommendation,
say what it costs — a rendering harness, a second runner, an afternoon — and let the plan
weigh it against everything else. A cost is something a planner can act on. A question is
something it can only defer.

**Go looking for them; they do not announce themselves.** These shapes have all produced real
open questions:

- A recommendation with more than one defensible form — a lint rule exemption or a move to a
  different file; repair the tests or delete them.
- A change that breaks the build unless something else is decided alongside it. Widening a
  coverage denominator past a configured threshold is the standard case.
- A change to the repository whose consequences reach outside testing. Committing a fixture
  directory that the running application also reads is the standard case.
- A configured rule that does not enforce what it says, where making it real and scoping it
  honestly are both defensible.
- Anywhere you wrote "either … or" in a recommendation and did not choose.

**You are not resolving these and you are not asking the user about them.** Stage one states
what is true; naming a question is a statement about what is undecided, which is itself true
and useful. Stage two turns each one into a decision the owner answers at their review gate.

Step 9b later requires every dependency edge to have identifiers at both ends, and any
endpoint that is a question becomes one of these. That path finds the questions that happen to
be dependency endpoints. This step exists because most of them are not.

If there are none, say "None." in the report rather than omitting the table — an absent list
and an empty one are different facts.

### Step 7d — Reconcile the run ledger, when there is one

Skip this step entirely if `docs/test-ledger.json` does not exist. A first assessment of a
repository has nothing to reconcile, and section 13 of the report is omitted with it.

```bash
python3 <test-reporting>/scripts/ledger.py docs/test-ledger.json --open
```

The run ledger is stage four's durable cross-run record, and R-7.2 of the reporting
requirements makes it **binding on this report**: every item it holds open must be explicitly
**confirmed** (still true), **updated** (changed, with evidence), or **contested** (wrong or no
longer meaningful, with evidence). An open item this report does not mention is a lint failure.

That rule is the planning linter's discharge discipline for open questions, lifted to the
pipeline level, and it exists because a document that simply does not mention a question reads
exactly like one that resolved it. It is the only mechanism under which an open defect provably
cannot vanish between runs.

**All three dispositions carry evidence, and `confirmed` needs it most rather than least.** It
is the disposition that costs nothing to write and asserts the most — that somebody looked and
the item is still true. Name what you looked at.

R-7.4 is the other half of the bargain and it is worth taking: once every open item is
reconciled, this assessment may state what changed since the ledger's last entry and **inherit
its unchanged conclusions with their prior evidence cited**, rather than re-deriving the whole
map. Say which run is the baseline, explicitly. Reconciliation is what converts a re-assessment
from a rebuild into a diff, so the entries replace work rather than adding to it.

Read `<test-reporting>/references/reconciliation.md` before writing the section. The
dispositions go into section 13 of the report as prose and into the index's `reconciliation`
array as data, and `check_index.py --ledger` checks the second against the ledger.

### Step 8 — Write the report

Write to `docs/test-assessment.md` (creating the directory if needed) unless overridden.
Follow `references/report-template.md` exactly; R-7.2 fixes the section order.

Include the `ID` column on the findings, exclusions, and degradations tables, and give each
recommendation its `R`-number heading. The machine-readable index is written later, in Step
9b, after
verification.

**Every path in every fenced code block is repository-relative.** Section 12 reproduces the
measurement, and a block containing `/Users/someone/Projects/...` reproduces it for exactly
one account on one machine. Write the skill's own location as a variable, defined once at
the top of the block, and write the repository as `.`:

```
SKILL=<path to the test-assessment skill>/scripts   # set this to wherever the skill lives
# Run from the repository root.
python3 $SKILL/detect_env.py --repo . --json > /tmp/env.json
```

This applies to every block in the report, not only Section 12 — a quoted command in a
finding has the same problem. `check_index.py` fails the report on an absolute home
directory path in any fenced block, so a slip here is caught in Step 9b rather than by
whoever tries to reproduce the numbers later.

Do not commit the file. Mention to the user that it was written and is uncommitted.

**Section numbering shifts by one when there is no run ledger.** Section 13 is the
reconciliation section and is omitted entirely in that case, which makes the machine-readable
index section 13 rather than 14. Both arrangements are correct; what is not correct is an empty
reconciliation section standing as ceremony.

### Step 9 — Verification pass

Unless `--no-verify` was given, spawn a **second agent with a fresh context** using the
Agent tool with `subagent_type: "general-purpose"`.

Give it only the drafted report and access to the repository. **Do not give it your
working context, your reasoning, or your confidence levels.** Its independence is the
entire value of the pass. Pass it the contents of `references/verification-brief.md`
along with the report path and repository path.

The verifier does not rebuild the analysis. It checks whether the report's claims are
true. It must check every finding in the top tier of the risk ranking in full, and a
sample of the remainder.

When it returns, resolve discrepancies **by returning to the evidence** — read the code,
the test, or the document in question yourself. Never average the two positions and never
prefer either agent by default. Where the evidence is genuinely ambiguous, leave the
finding in the report marked `[contested]` with both readings stated, because a contested
finding is useful input to the planning stage.

Then update the report's Verification section with what was checked, which claims were
corrected, which are contested, and which portions were verified in full versus sampled.

If the verification pass could not run, the report must say so and is marked lower
confidence.

### Step 9b — Emit the machine-readable index

**Do this after Step 9, never before.** Verification applies corrections; an index written
before it describes a report that no longer exists. This is the whole reason the step sits
here rather than beside Step 8.

Write the report's machine-readable index: one fenced block whose info string is exactly
`json assessment-index`. `references/index-schema.md` specifies every field normatively.

The index carries stable identifiers so the planning stage can reference a finding and have
the reference survive a correction. Positional numbering does not survive — this skill's
verification pass corrected nineteen claims in one real run, and any correction that merges
or splits a finding renumbers everything below it.

1. **Assign identifiers** in the order the report presents things: `F` for findings, `R` for
   recommendations, `X` for exclusions, `D` for degradations, `Q` for open questions. Add the
   `ID` column to the findings, exclusions, and degradations tables in the prose.
2. **Copy, do not re-derive.** Every value in the index must already be stated in the prose
   above it. The index is a projection of the report, not a second analysis. In particular,
   `basis` on each metric is the label Step 7b already assigned — carry it forward, do not
   decide it again.

   **One deliberate exception: `testability`.** Its per-function entries are a machine
   interface, and restating forty-seven function names in prose would bury Section 8's
   actual finding under a table nobody reads. The exception is paid for rather than waived —
   the prose states each category's count and share and the scope rule, and `check_index.py`
   recomputes both from the entries and fails on a mismatch. Write Section 8's table from
   the entries so the two cannot disagree.

2b. **Emit `testability` and `testability_scope`** from the classification Step 6 made.
   `complexity.py` supplies `name`, `line`, and `end_line` for each function under
   `files[].functions[]`; copy them rather than reading line numbers off the source. Set
   `complete` to `true` only when the classified set really is every function in the
   repository — that flag is what tells the planner whether a claim it cannot resolve is a
   mistake or a backfill request, and getting it wrong turns one into the other.
3. **Give every dependency edge two identifiers.** An edge whose other end is free text —
   "the threshold decision" — is one the planner cannot resolve. Turn such an endpoint into
   an open question with a `Q`-number.
4. **Validate before finishing:**

   ```bash
   python3 <skill>/scripts/check_index.py <report path>
   python3 <skill>/scripts/check_index.py <report path> --ledger docs/test-ledger.json
   ```

   It checks the schema, the identifier patterns, the closed enumerations, the acyclicity of
   the dependency graph, and — the part that matters most — that every identifier in the
   index appears in the prose and every identifier in the prose is defined in the index. Fix
   every problem it reports. Do not finish with a failing index.

   **Run the second form only when the repository has a run ledger**, and then run it always.
   It checks R-7.2: every open ledger item confirmed, updated, or contested, each with
   evidence. It names any item this report dropped. Nothing else in the pipeline can catch a
   dropped one, because a dropped item leaves no trace to catch.

**Backfill mode.** When asked to add an index to a report that already exists, do only this
step. Read the report, assign identifiers to what it already says, add the three `ID`
columns, write the index, and validate it. **Do not re-measure and do not re-derive
anything** — the report has already been verified, and re-running the analysis would produce
a report the verification pass never saw. If a backfill turns up a genuine internal
contradiction in the report, record it as a contested item in the index rather than deciding
it, and say so to the user.

**Backfilling reconciliation into a version 1.1 index** is the narrowest case of all. A 1.1
index predates the run ledger and is not malformed. If the repository has no
`docs/test-ledger.json`, set `index_version` to `1.2` and change nothing else. If it has one,
run Step 7d, add section 13 and the `reconciliation` array, and set the version. Nothing is
re-measured either way.

**Backfilling testability into a version 1.0 index** is the narrower case, and it is what
the planning stage asks for when it hard-stops on a report written before the section
existed. Do only this:

1. Run `complexity.py` for the function enumeration. This is a measurement of the code, not
   a re-derivation of the report's judgments, so it is permitted here — but if its figures
   now disagree with the report's, stop and say so rather than quietly updating them. A
   disagreement means the repository moved since the assessment ran, and that is the user's
   decision, not a backfill.
2. Classify the bounded set of Step 6, using the report's own risk tiers and recommendation
   locations. The judgments come from what the report already says about each function; you
   are recording them at function granularity, not forming new ones.
3. Rewrite Section 8's table so its counts and shares come from those entries, and add the
   scope paragraph. This is the one prose change a testability backfill makes.
4. Add `testability` and `testability_scope`, set `index_version` to `1.2`, and validate.

If the report says nothing about a function you must classify — it sits in a tier the map
summarized rather than enumerated — classify it from the code and mark it in the entry's
`note`. That is reading, not re-deriving. What you may not do is revise a testability
judgment the report already states.

## Degradations to record

Every one of these that applies must appear in the report's Degradations section:

- No requirements material found (inference mode)
- No test suite present
- Test suite present but broken
- Some tests failing
- Suite stopped at the time budget
- Coverage tooling unavailable or not configured
- Mutation testing skipped, with the reason
- No version control history (risk ranking loses change frequency)
- Language outside the supported set (no measured complexity)
- Verification pass skipped

## Repeatability

A second run against the same unchanged repository must reach substantially the same
conclusions. Anchor judgments to quoted evidence rather than impressions, and use the
fixed catalogs in `references/` rather than inventing categories, so two runs land in the
same place.

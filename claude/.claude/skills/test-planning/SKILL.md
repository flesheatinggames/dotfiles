---
name: test-planning
description: Turn a verified test assessment report into an executable plan at docs/test-plan.md — work items grouped into vertical slices, with behavioral claims, escalations, a defended coverage target, and a recorded wave schedule, ready for the owner to review. Use when asked to plan test work, decide what to test first, or act on a test-assessment report. Read-only with respect to the repository; the plan file is its only write.
---

# Test Improvement Planning

Stage two of a four-stage test improvement workflow. This stage plans. It does not assess,
write tests, or execute the plan.

Its input is a verified assessment report. Its output is `docs/test-plan.md`, reviewed by
the owner before stage three executes it. That review is where inferred behavior gets
ratified, where document-versus-code conflicts get decided, and where the coverage target
gets approved.

**The design goal that shapes everything below: the executor must never exercise judgment
about *what* to build, only about *how*.** Every decision that weighs risk, scope, or
intent is made here or escalated to the owner. If stage three is making those calls
mid-run, this plan has failed.

## Absolute rules

1. **Read-only except the plan file.** Never modify, create, or delete production code, test
   code, or configuration in the target repository — **including coverage configuration**.
   Writing the exclusion list into the coverage tool is slice zero's job, and it belongs to
   stage three. Planning it is not doing it.

2. **Never stop to ask.** Do not use `AskUserQuestion`. Every question the plan cannot answer
   becomes an entry in the decisions-required section and the run continues (R-6.1). A plan
   in which every item is blocked is a legal plan and a useful one — it tells the owner
   exactly what their answers unlock. A run that stopped halfway to ask something is a
   failure, because the owner then has to answer a question with no plan in front of them.

3. **Never fabricate.** A claim you cannot source is not emitted. A target area you cannot
   understand well enough to derive claims for is escalated, not guessed at. A baseline the
   assessment did not record is not invented as zero.

4. **Never silently choose a side in a conflict.** Whichever side a test asserts gets
   enshrined. Recording a visible recommendation is fine and often helpful; writing a work
   item that quietly asserts one reading is not.

5. **Never re-derive the assessment.** The risk ranking, the testability classification, the
   exclusion list, the seam recommendations, and the document inventory are given. Where you
   believe the assessment is wrong, resolve it by reading the evidence, record the
   disagreement in the plan, and move on — do not substitute your own analysis for it.

6. **Plan for as much as you can execute, and state what you left.** The value line bounds
   which *findings* are planned for; it says nothing about how much of the code the plan
   reaches, and those come apart. A plan can sit above the value line on every finding and
   touch a third of the repository. `plan-meta.scope` records the two figures the linter
   recomputes — reachable classified functions, and how many your claims actually locate on —
   so the proportion is on the page rather than in nobody's head.

   **The backlog is not a way of declining work.** It is for work the charter forbids
   (production changes), work a blocker prevents, or work that is a different kind of thing
   (installing new tooling for a new class of test). Work that is merely *more of the same*
   belongs in the plan. Two symptoms that this rule is being broken, both from a real plan
   that deferred two thirds of a repository: a backlog entry whose reason is that doing one
   first makes the pattern reviewable, and a backlog entry standing in for an open question
   that was never really open.

7. **Every cited claim carries its quote inline.** Section 14 of the requirements says a
   competent reviewer reading only the plan file must be able to make every decision it asks
   of them without opening the repository. A citation they cannot check is the one thing the
   human gate cannot check cheaply, so the quote travels with the claim.

## Inputs

| Option | Meaning | Default |
|---|---|---|
| `--assessment <path>` | The verified assessment report | `docs/test-assessment.md` |
| `--output <path>` | Where the plan is written | `docs/test-plan.md` |
| `--value-line <tier>` | Lowest risk tier to plan for | suggested by `read_assessment.py` |
| `--areas <n>` | How many claims-derivation readers to fan out to | 5 |

If the user gave hints in prose rather than flags, use them the same way.

## Procedure

### Step 1 — Read the assessment

```bash
python3 <skill>/scripts/read_assessment.py <assessment path> --json
```

**When it reports no index, stop.** It prints the backfill instruction; relay it and end the
run. This is the one place the skill does not degrade, and the reason is specific: stage
one's "degrade, do not fail" rule covers deficiencies in the target repository, not stage
two's own input contract. A plan built by guessing at an unindexed report carries references
that resolve to nothing, and the linter's completeness rule — the only thing standing between
the plan and a silently dropped top-tier finding — would have no finding list to check
against. Degrading here produces a plan that looks complete and is not.

**The same applies when it reports no testability section.** An index at schema version 1.0
predates that section, and an index at 1.1 must carry it. Either way the script prints a
narrower backfill instruction — classify these functions, re-emit the index, nothing
re-measured — and the run stops. The claim-enablement rule cannot run without it, and a
planner that assumes every target is reachable is exactly what produces claims asserted
through an extraction no item performs.

Note what the script tells you about scope: `complete` false means the assessment classified
a bounded set, so a claim you write against a function outside it will hard-stop at lint
time. That is recoverable — the linter names the exact locations to backfill — but it costs
a round trip, so prefer targets inside the classified set when the choice is free.

Record every degradation the assessment declares, **and what each one costs this plan**
(R-13.3). "Inherited D4" is not the requirement; "inherited D4, so R2's characterization test
can only exercise the empty case and the seam is scheduled behind a decision" is.

Read the assessment's prose too, not only its index. The index carries identifiers and
classifications; the argument behind them is in the text, and you need it to write slice
rationales that mean anything.

### Step 2 — Resolve contested findings and internal inconsistencies

`read_assessment.py` lists every contested item. R-4.3 forbids building a work item on one as
it stands. For each, do one of exactly two things:

- **Resolve it by reading the evidence yourself.** Read the code, the test, or the document.
  Record the resolution in the plan's `assessment_resolutions`, stating what you read and what
  it showed. This is not re-deriving the assessment; it is settling one question the
  assessment left open.
- **Escalate it** as a `decision` block naming the finding, laying out both readings, and
  saying what would settle it.

**The same duty applies to inconsistencies you find inside the assessment**, and you will find
some. One real report states 325 production files in one section and records 324 as a
correction in another; another states a figure of 720 in a recommendation that a later
correction moved to 2,070. Do not pick the number you prefer and do not average them. Read
enough to settle it, record the resolution, or escalate. An unresolved inconsistency that
reaches a work item becomes a target nobody can check.

Recommendations the assessment marked `safe_to_execute: false` get the same treatment.
Scheduling one anyway overrides a judgment stage one already made.

### Step 3 — Set the value line and declare scope

The value line is the boundary below which findings are not planned for.
`read_assessment.py` suggests one; the suggestion is a default, not an answer. Raise it when
the work above it will not fit a review sitting, and say so.

Everything above the line is either covered by a work item or listed in the plan's explicit
exclusions with a reason (R-9.1). The linter enforces this and it is its most important rule.
**A backlog entry does not discharge a finding above the line** — the linter reports that as
`finding-only-backlogged`. Declining work is a decision, and a decision belongs in an exclusion
where it carries a reason and a source that the owner reads at the gate.

Then set the scope, which is a different question from the value line and is easy to skip:

```bash
python3 <skill>/scripts/plan_lint.py <plan path> --assessment <assessment path> --scope
```

It prints both figures and **names every reachable function no claim locates on**. Read that
list before you accept it. A plan reaching under half of what is reachable has to justify it in
at least two hundred characters, and "the rest is in the backlog" is not a justification — it
says where the work went, not why it did not happen here. Check the claim budget while you are
there: at eight slices of eight to twenty-five claims the ceiling is about two hundred, and a
plan using fifteen of them was not constrained by anything but appetite.

Write the exclusions now, while the reasoning is fresh: the assessment's own exclusions
inherited forward, everything below the value line, and anything this plan declines for a
reason of its own. Each exclusion says which of the three it is.

### Step 4 — Partition the target areas

```bash
python3 <skill>/scripts/partition.py --assessment <path> --repo . --areas 5 --json > /tmp/partition.json
```

It builds the finding-to-file map, counts how many findings touch each file, chooses between
a per-finding and a per-module split from those counts, bin-packs the areas by line count, and
emits the **ledger** — every file and, where names are available, every symbol the derivation
pass is accountable for.

Pass `--complexity <complexity.py output>` when the assessment recorded exact function counts;
it turns the ledger from file granularity into symbol granularity, which makes the
completeness gate in Step 6 much sharper.

### Step 5 — Fan out claims derivation

Read `references/claims-derivation.md` and follow it exactly. In brief: one read-only subagent
per area, **all spawned in a single message** so they run concurrently, each with the verbatim
prompt from that file, its own disjoint file list, and the output schema.

R-5.5 requires this to run **once, up front, over the whole plan scope** — not per slice — so
the owner can ratify the pinned set and resolve escalations in one sitting rather than being
interrupted repeatedly.

### Step 6 — Merge, and check both gates

```bash
python3 <skill>/scripts/merge_claims.py /tmp/area-*.json --ledger /tmp/partition.json --json
```

The merge deduplicates claims several areas derived from the same document statement, unions
every location each applies to, and assigns stable identifiers.

**Both gates must pass before you build a single work item.**

- **Gate A — ledger completeness.** Every file and symbol a reader was accountable for is
  either named by a claim or carries an explicit reason for having none. A reader that read
  half its area produces a short answer, and a short answer looks exactly like a small area;
  this gate is the only thing that tells them apart. When it fails, re-run that reader or
  record the reason. **Never close the gap by removing entries from the ledger.**
- **Gate B — claim budget.** At most eight slices of eight to twenty-five claims, so roughly
  two hundred. Over budget means the value line is too low for one review sitting. Raise it,
  re-partition, and record the narrower scope in the exclusions. **Never drop claims silently
  to fit.**

Then build the ratification list: every claim, pinned ones first, each with its source and —
for cited claims — its quote.

### Step 7 — Triage the conflicts

The readers return conflicts. Sort each into exactly one of three classes using
`references/conflict-catalog.md`, which gives a recognition test for each:

| Class | Is | Becomes |
|---|---|---|
| `flagged` | Documented behavior with no implementing code | A note to the owner. **Never a work item and never a blocker** |
| `escalation` | Code contradicts a document | A `yaml escalation` block, blocking the items that depend on the answer |
| `decision` | A scope or approach choice you are not authorized to make | A `yaml decision` block |

The third class exists because the first two do not cover everything. One real case: whether
to commit a fixture directory to a repository, given that the build tool's root-relative
globs mean such a directory changes what the dev server shows and what the build ships. That
is neither a missing implementation nor a contradiction — it is a choice with consequences
outside testing. Without a third class the planner has to mislabel it or decide it silently,
and deciding it silently is rule 4.

**Where an answer changes what a blocked item is, say so on the answer.** Each option may
carry an `effect`: the rewrite that answer implies per item — dropping it, replacing fields,
removing checks that no longer apply, changing which claims it asserts. Write the item out as
one answer, say in its justification which one, and let the others state their diffs.

Do not put the difference in the item's prose. "This check applies only under option a" makes
the item two pieces of work wearing one identifier, and a completion check qualified by a
sentence is not machine-checkable as written, whatever R-7.1 asks for — the executor has to
interpret it. The linter reports this as `conditional-prose`, and it exists because the defect
appeared eleven times across three plans that were otherwise clean.

### Step 8 — Build slice zero, then the slices

Read `references/slice-construction.md`.

Slice zero is mandatory and contains only infrastructure. Where a test framework already
exists, its first item **degrades to verify-and-baseline**: confirm the suite runs, write the
assessment's exclusion list into the coverage configuration, and record the first number
produced so it is already the effective one. Skipping the slice is not the alternative —
every coverage delta in the plan would then be stated against a baseline that is about to
change.

Then the slices, vertical: one coherent target area carried from its current state to
verified unit tests, in dependency order — characterization first where the assessment
required one, then the seam, then the unit tests.

Two deviations from risk order are permitted, and each carries a justification: pulling a
slice forward because a later slice depends on its seam, and demoting a slice every one of
whose items is blocked. The second exists because the alternative is a plan whose first
executable step is a slice nobody can execute.

**Write a mutation check for every claim as you write the item, not afterwards.** Each claim
a `unit-tests` or `test-repair` item asserts needs either a `mutation` check naming it or one
`mutation-waiver` entry naming it. This is the single largest source of first-draft lint
failures, and doing it at the end means going back through every item.

It is more mechanical than it sounds, because a well-formed claim nearly dictates its own
mutation: a claim that a query is scoped names the filter to delete, a claim of a fallback
names the default to change. **If you cannot see the edit, suspect the claim before you reach
for a waiver** — a claim too vague to falsify is usually too vague to write a test from
either, and sharpening it fixes both. `references/schema/completion-checks.md` gives the
patterns and the standard the waiver is held to.

**Check each claim's target against the assessment's testability data before you assert it.**
A claim whose function is classified `export-only` or `needs-seam` can only be asserted by an
item that depends on the work making it reachable, and a claim on a function classified
`integration-only` or `excluded` should not be planned at all. The linter enforces the
dependency; catching it here saves rebuilding the slice. `references/slice-construction.md`
covers what to do when the enabling item lands in a later slice than the assertion.

### Step 9 — The mandatory label audit

**Do this every time.** It is the analogue of the assessment skill's Step 7b, which exists
because that failure recurred across consecutive reports, and vigilance alone did not prevent
it.

Go through every claim on the ratification list and check its label against its source, one at
a time:

- **`cited`** requires a document, a location in that document, and the document's own words
  quoted. If you are reasoning from a name, a docstring, a test, or a commit message, it is
  not cited.
- **`pinned`** requires a code location and the line quoted. Everything read from the code is
  pinned, however obviously correct it looks.
- **`ratified`** must not appear at all. Ratification only ever results from owner review.

The two errors are not symmetric, and it is worth being clear about which one to fear.

A claim wrongly marked `pinned` costs the owner a needless decision: they read it, see it is
already specified, and approve it. Annoying, recoverable.

**A claim wrongly marked `cited` enshrines something nobody ratified.** It skips the
ratification list entirely, a test gets written asserting it, and from then on the behavior
has the standing of a specified requirement because a passing test says so. Nobody ever
agreed to it. When you are unsure, label it `pinned` — the cost of being wrong runs one way.

Then audit the numbers the same way. Every figure in the target proposal is `measured` or
`estimated`, copied from the assessment's own label. A target derived from an estimate must
say so.

### Step 9b — Read the run ledger, when there is one

Skip this entirely if `docs/test-ledger.json` does not exist.

```bash
python3 <test-reporting>/scripts/ledger.py docs/test-ledger.json --open
```

The run ledger is stage four's durable cross-run record of what earlier runs left unfinished:
defects the owner decided but nobody has fixed, disputes nobody answered, documents flagged as
wrong, findings about the pipeline, and work items that never delivered.

**Your obligation to it is consistency, not itemised discharge** (R-7.3 of the reporting
requirements). Two rules, and the linter checks both:

1. **A work item whose footprint touches a file carrying an open defect names that defect** in
   a `known-defects` field. You are entitled to plan nothing about an open defect — fixing it
   may be somebody else's work, or scheduled for a later cycle. What is never legitimate is
   planning work *on top of* one without saying so, because the executor will then write tests
   in a file where something is already known to be broken and have no way to find that out.

2. **A claim the ledger already records at `cited` or `ratified` authority is not re-derived as
   new work.** Either it is the same claim, in which case it already carries its authority and
   the ratification list should not ask the owner for it a second time, or the identifier has
   been reused — which is worse, because every ledger reference to it now resolves to the wrong
   statement.

The obligation stops there deliberately. Section 11 of the reporting requirements defers the
question of whether the planner should be bound as strictly as the assessment — which must
discharge every open item — until a real multi-run sequence shows where planner-side drops
actually occur. Read `<test-reporting>/references/reconciliation.md` for the full argument.

An open ledger item is also raw material: an undelivered work item from a previous run is a
gap somebody already scoped, and a corrected dispute carries the claim text the last run said
should have been written.

### Step 10 — Target, waves, lint, write

Derive the target using `references/target-derivation.md`. State it as a delta with a
re-derivation trigger whenever slice zero changes the denominator, because a target approved
against a denominator that is about to stop existing has not really been approved.

Compute the wave schedule:

```bash
python3 <skill>/scripts/plan_lint.py <plan path> --waves
```

Paste the block it prints. The schedule is derived, not authored; the linter recomputes it and
fails on a mismatch.

Lint until clean:

```bash
python3 <skill>/scripts/plan_lint.py <plan path> --assessment <assessment path>
python3 <skill>/scripts/plan_lint.py <plan path> --assessment <assessment path> \
        --ledger docs/test-ledger.json
```

**Always pass `--assessment`.** Without it the completeness rule does not run, and that rule
is the one that stops a top-tier finding being dropped silently. The linter says so when you
omit it.

**Pass `--ledger` whenever the repository has one.** It checks the two consistency rules from
Step 9b and names which item owes which defect. Without a ledger the flag is dropped.

The linter also takes `--phase`, defaulting to `planned`. A handful of rules mean different
things at different points in a plan's life: a freshly written plan must carry no resolutions
and no ratified claims, a reviewed one is expected to carry both, an executed one carries
statuses the first two forbid, and a closed one carries stage four's record of the owner's
answer to every defect. Leave the default when writing a plan. Pass `--phase reviewed` after
the owner's sitting, `--phase executed` when stage three has written status back, and
`--phase closed` after stage four's close-out gate.

Write the plan to `docs/test-plan.md` following `references/plan-template.md`, which fixes the
section order (R-12.2). Do not commit it. Tell the user it was written and is uncommitted, and
point them at `references/review-brief.md` for what the review sitting involves.

## No verification agent

Stage one runs a fresh-context verification agent and it earns its keep there. Stage two does
not, deliberately.

The deterministic linter checks form. The human gate checks substance. An agent between them
would re-check what the owner is about to check anyway, at the cost of a full extra pass over
a document written to be read by a person. The one thing the owner genuinely cannot check
cheaply — whether a `cited` label is truthful — is handled by the mandatory inline quote and
by Step 9, not by another agent.

## Degradations to record

Every one of these that applies goes in the plan, with what it cost:

- Any degradation the assessment declared, each with its cost to this plan
- The assessment's verification pass was skipped, so every finding is single-sourced
- Complexity or function counts are estimates rather than measurements
- The per-file coverage baseline is incomplete, so some deltas start from an unknown baseline
- No coverage baseline at all, so the target is a delta against a denominator slice zero establishes
- A contested finding was escalated rather than resolved, so its slice is entirely blocked
- A recommendation the assessment marked unsafe to execute was escalated rather than scheduled
- Claims derivation could not reach some part of a target area, with exactly which part

## Repeatability

A second run against the same assessment and the same unchanged repository must produce
substantially the same plan. The deterministic parts are deterministic by construction: the
partition, the merge, the identifiers, and the wave schedule all sort their inputs. Anchor the
judgment parts — slice boundaries, claim wording, the target argument — to what the assessment
states and to quoted evidence, rather than to impressions.

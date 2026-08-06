# Plan Template

The section order below is fixed by requirement R-12.2. Do not reorder it. Omit a section only
when it does not apply, and when you omit one, say why rather than letting it vanish.

The order is not arbitrary. It is the order the owner works through at review: what they have
to decide, then what the plan will and will not do, then what it is aiming at, then the claims
they ratify, then the work itself. Anything that asks something of the reader comes before
anything that merely informs them.

Replace every angle-bracket placeholder. A placeholder left in the output is a defect.

**One file, both audiences** (R-7.2). Each work item is a fenced YAML block; the narrative
lives in prose between the blocks. A separate machine-readable file is prohibited, because
paired files drift apart — the same reasoning that puts stage one's index inside its report.

---

````markdown
# Test Improvement Plan: <repository name>

Generated <date> by the `test-planning` skill (stage two of four), from
`<assessment path>` at commit `<sha>`.

<One paragraph. What state the suite is in according to the assessment, what this plan will
do about it, and what it needs from the owner before stage three can start. Lead with the
answer.>

```yaml plan-meta
plan_version: "1.0"
repository: <name>
assessment_path: <path>
assessment_commit: <sha or null>
generated: "<YYYY-MM-DD>"
value_line:
  lowest_tier_planned: <top | high | medium | low>
  rationale: >
    <Why the line is here. What it excludes and why that is the right scope.>
inherited_degradations:
  - id: <D1>
    cost_to_this_plan: >
      <What this degradation costs THIS PLAN, not what it cost the assessment. R-13.3.>
assessment_resolutions:
  - ref: <F4>
    issue: >
      <The contested finding or internal inconsistency.>
    resolution: >
      <What you read and what it showed. Or: escalated as DEC-01.>
```

## 1. Decisions required

<Everything the plan could not decide. Each entry is one of three classes — see
`references/conflict-catalog.md`. Say plainly at the top of this section that none of them
stops the plan: every unblocked item is executable while these are open, and an unresolved
entry degrades scope rather than blocking the run (R-6.4).>

### <E1> — <short title>

```yaml escalation
id: E1
class: escalation
title: "<what contradicts what>"
assessment-ref: [<F1>]
document-side:
  location: <path:line>
  quote: "<the document's own words>"
code-side:
  location: <path:line>
  quote: "<the code's own words>"
options:
  - id: E1-a
    summary: "<resolution>"
    consequence: "<what it costs>"
  - id: E1-b
    summary: "<the other resolution>"
    consequence: "<what that costs>"
recommendation: <a visible recommendation, or null>
blocks: [<WI-05>]
resolution: null
```

### <DEC-01> — <short title>

```yaml decision
id: DEC-01
class: decision
question: "<the question, as a question>"
context: >
  <Enough that the owner does not have to reconstruct it. Where an experiment would
  settle it, say what the experiment is.>
assessment-ref: [<F4>]
options:
  - id: DEC-01-a
    summary: "<option>"
    consequence: "<which items change, and how>"
  - id: DEC-01-b
    summary: "<option>"
    consequence: "<…>"
recommendation: <or null>
blocks: [<WI-07>]
resolution: null
```

### <FLAG-01> — <short title>

```yaml flagged
id: FLAG-01
class: flagged
title: "<documented behavior with no implementing code>"
assessment-ref: [<F3>]
documented-behavior:
  location: <path:line>
  quote: "<…>"
evidence-of-absence: >
  <How you established the code is absent: the searches you ran, not the conclusion.>
note: >
  <Why this is a note and not a work item: writing production code is outside this skill's
  charter, and the finding is invisible to coverage tooling because coverage cannot report on
  code that does not exist.>
```

## 2. Scope and exclusions

<What the plan will not do, and why (R-9.1). Three sources: the assessment's own exclusions
inherited forward, everything below the value line, and anything this plan declines for a
reason of its own. Every entry says which.>

```yaml exclusion
id: PX-1
scope: [<path or glob>]
reason: >
  <Inherited, below the line, or the planner's own reason.>
source: <inherited | below-value-line | planner>
assessment-ref: [<X1>]
```

## 3. The target proposal

<The argument in prose, then the block. `references/target-derivation.md` gives the three
codebase shapes and which form each admits.>

```yaml target
form: <absolute | delta | delta-with-rederivation>
axes:
  - name: <what this axis measures>
    metric: <precisely, including the denominator>
    from: "<baseline, with its basis>"
    to: "<target>"
    basis: <measured | estimated | unknown>
rederivation_trigger: <what changes the denominator and when to re-derive, or null>
argument: >
  <Why this number, why this form, and what the target does not cover. At least a hundred
  characters, which is a floor against an empty field rather than a standard.>
approved: null
```

## 4. Claim ledger and ratification list

<Open with the counts: how many claims, how many cited, how many pinned. The pinned ones are
what the owner approves; approving one relabels it `ratified` in place and adds who approved
it and when.

Say why the cited ones carry their quotes: so the reviewer can check the label without opening
the repository, which is the one thing the human gate cannot otherwise do cheaply.

**Group the claims so the review can work through them area by area**, and say in the opening
sentence how many need action. Grouping by area beats a strict cited-then-pinned order,
because an owner ratifying claims about one module wants them together; what matters is that
the count of pinned claims is stated up front so nobody discovers halfway through how much
the sitting involves.>

```yaml claim
id: C1
text: "<one sentence, precise enough to write a test from>"
label: <cited | pinned>
source:
  kind: <document | code>
  location: <path:line or path §n>
  quote: "<its own words — mandatory for cited>"
locations:
  - <path:line>
notes: >
  <Only when the claim needs a caveat — for instance, that it deliberately says nothing
  about a point an escalation covers.>
```

### Inconsistent pinned pairs

<Only when two pieces of code duplicate the same logic and differ, with no document covering
either. Present the pair together, name both claims, and say that ratifying one is what turns
the inconsistency from a curiosity into a bug report.>

## 5. Slices

### Slice zero — <title>

<Why it exists here, and — when a test framework already exists — that its first item degrades
to verify-and-baseline rather than the slice being skipped.>

```yaml slice
id: S0
title: "<…>"
area: <…>
rationale: >
  <…>
items: [<WI-01>]
```

```yaml work-item
<see references/work-item-schema.md>
```

### <S1> — <title>

<One paragraph per slice: what area it covers, why it is at this position in the order, and
anything about it the owner should know before approving. Where the slice carries a deviation
from risk order, the justification is in the block and the reason is here in prose.>

```yaml slice
id: S1
title: "<…>"
area: <…>
rationale: >
  <…>
items: [<WI-02>, <WI-03>, <WI-04>]
depends-on: [S0]
deviation:
  kind: <pulled-forward-for-seam | demoted-fully-blocked>
  justification: >
    <Only when the slice deviates from risk order.>
```

<Then its work items, in dependency order.>

## 6. Wave schedule

<One sentence: recorded as information, not instruction (R-10.2); execution is sequential in
this version; the schedule exists so that enabling concurrency later is a change to the
executor alone.

Do not author this block. Run `plan_lint.py <plan> --waves` and paste what it prints; the
linter recomputes it and fails on a mismatch.>

```yaml wave-schedule
computed_by: plan_lint.py
note: >
  <Anything worth explaining — most often why slice zero occupies a wave alone.>
waves:
  - wave: 1
    slices: [S0]
    reason: "<…>"
```

## 7. Optional backlog

<Work beyond the approved target. Once the target is met, pursuing any of it takes a fresh
decision; none of it is an obligation (R-9.3).>

```yaml backlog-item
id: BL-1
title: "<…>"
reason: >
  <Why it is backlog rather than a slice.>
assessment-ref: [<D2>]
```

## 8. Degradations inherited

<Every degradation from the assessment, with what it cost this plan. The `plan-meta` block
carries the machine-readable version; this is where a reader sees it. If none applied, say
"None." rather than omitting the section.>

| ID | Degradation | What it cost this plan |
|---|---|---|
| <D1> | <…> | <…> |

## 9. How this plan was produced

<Short. What ran, in what order, so a later stage can reproduce it. Repository-relative paths
and a variable for the skill location — never absolute paths.>

```
SKILL=<path to the test-planning skill>/scripts   # set this to wherever the skill lives
# Run from the repository root.

python3 $SKILL/read_assessment.py docs/test-assessment.md --json > /tmp/assessment.json
python3 $SKILL/partition.py --assessment docs/test-assessment.md --repo . --areas <n> --json > /tmp/partition.json
# <n> read-only subagents, one per area, spawned in a single message
python3 $SKILL/merge_claims.py /tmp/area-*.json --ledger /tmp/partition.json --json > /tmp/claims.json
python3 $SKILL/plan_lint.py docs/test-plan.md --waves
python3 $SKILL/plan_lint.py docs/test-plan.md --assessment docs/test-assessment.md
```

Lint status at the time of writing: <clean>.
````

---

## Notes on writing the prose

**The prose is not decoration.** Requirement section 14 says a competent reviewer reading only
this file must be able to make every decision it asks of them without opening the repository.
The YAML blocks carry the facts; the prose carries the reasoning that makes a decision
possible. A plan that is all blocks is a plan the owner cannot review.

**Say what is blocked and what is not, early.** The first thing an owner wants to know is
whether they have to answer everything before anything can start. Usually they do not, and the
decisions-required section should say so in its first sentence.

**Do not restate a block in prose beside it.** Say the thing the block cannot: why this
position in the order, what the alternative was, what will look surprising when it happens. A
coverage number falling from 94.95% to roughly 33% is the correction of a measurement error
and it will look like a catastrophe; that sentence belongs in the prose, next to the item that
causes it.

**Keep the file readable end to end.** It is a review document. If it is too long to read in a
sitting, the slices are too many or the value line is too low, and both of those are fixable
before the owner ever sees it.

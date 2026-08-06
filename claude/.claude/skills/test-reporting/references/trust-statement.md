# The trust statement (R-5.6)

The last section of the report and the only one with rules about its shape as well as its
content. It answers the question the whole pipeline exists for — what may now be relied on —
and it is the section most likely to be quoted out of context, which is why what it may not say
is specified as tightly as what it must.

## The one sentence it may never say

**No scalar.** No grade, no score, no letter, no percentage of overall health, no
"production-ready", no "fully tested", no "the suite can be trusted".

The argument is not modesty. This pipeline exists to earn the sentence "you can run this suite
and trust it", and that sentence is not true as a scalar — trust is not one quantity. It is
true of some behaviors and false of others, and which is which is the entire content of the
report. A grade compresses that into one symbol, and what it compresses away is exactly the
voids: the areas nobody tested, the claims nobody ratified, the coverage figure that measures
which lines ran rather than whether anything would notice them changing.

A grade would be the report-level version of the vanity coverage number this project exists to
kill. `trace_report.py` fails the assembly on one, and the patterns it matches are deliberately
crude — they will not catch a determined evasion, and they are not meant to. They catch the
sentence a well-meaning writer reaches for at the end of a good run.

## What it is instead

A bounded map, with the terrain marked and the voids marked.

Four things, and the last is the one people leave out.

### 1. Every positive claim cites its evidence class

Three classes, in descending strength:

| Class | Means | Earned by |
|---|---|---|
| **Mutation-surviving assertion** | A named edit to the code makes this test fail. The suite would notice this behavior changing. | A mutation check recorded `passed` |
| **Passing assertion** | The test passes and asserts something specific, and nothing has shown the suite would notice it breaking. | A test with real assertions and no mutation check, or one waived |
| **Characterization pin** | This is what the code does. Nobody has said it is right. | A `pinned` or `ratified-as-observed` claim |

Attributing a class a claim did not earn is forbidden by R-9.2 and it is the easiest mistake
here, because the language is close: "verified", "confirmed", "checked" all read as the top
class and are earned by none of them on their own. Say which of the three, per claim or per
group of claims, using the evidence column of section 2.

A mutation check recorded `suspended` earns nothing. It was suspended because the claim's test
is already red in the defect registry, and mutating code against an already-failing test proves
nothing. It becomes evidence when the test goes green and not before.

### 2. Unknowns and exclusions stand beside what is known

Not in a separate section, not at the end, not in smaller print. In the same paragraph as the
corresponding positive statement, wherever a reader would otherwise generalise from it.

If three of eleven modules are covered, the sentence that says what is now asserted about those
three says in the same breath that the other eight are untouched. A reader who takes away "the
parsing is verified" from a report that verified the parsing and nothing else has read the
report correctly and been misled by it, and that is the report's fault.

### 3. No unbounded claim

"Verified" needs an object: verified *what*, against *what statement of correct behavior*.
"Covered" needs the same. The unbounded forms — "the module is tested", "input handling is
verified" — are the shapes a scalar takes when it has been broken into pieces, and they are
worse than a grade because they read as specific.

### 4. It carries its time dimension, and this is the half that gets left out

Trust decays. The suite is static and the code is not, so every statement here is true of one
commit and progressively less true of every commit after it.

Nothing can measure that decay directly. What can be measured is how far the code has moved,
which is why the statement is dated to the run's closing commit rather than to a day, and why
later runs report the commit distance since the last close-out. The preamble table carries
both. Use them: a statement dated to a commit two hundred commits back is a different statement
from the same words dated to yesterday's, and the number is right there.

For a first run there is no baseline and the commit distance is not applicable. Say that rather
than omitting the paragraph — "this is the first closed run, so there is nothing to measure
decay from" is information.

## A worked shape

Not a template to fill in — the content is specific to each run — but the shape a statement
with all four properties tends to take.

> As of commit `a1b2c3d`, closed on 2026-08-04, the following can be relied on.
>
> **Four behaviors of the amount parser are asserted against edits that would break them.**
> Each has a mutation check that passed: a named change to the parser makes the corresponding
> test fail. Two of the four are specified in `docs/spec.md` and quoted in the plan; the other
> two are behaviors you confirmed at the review sitting. *Nothing else in the parser is in this
> class* — the rounding behavior in particular is asserted by a passing test with no mutation
> check, so nothing has shown that the suite would notice it changing.
>
> **The ledger reader is characterized rather than verified.** Its two claims record what the
> code does; nobody has said that is what it should do. A failure there means something
> changed, not that something broke, and it is worth exactly that much.
>
> **The report renderer is untouched by this run.** Its twelve tests execute it and assert
> nothing, which the assessment found and this run did not reach. Coverage reports it at 100
> percent of lines, and that figure means only that the lines ran.
>
> **One specified behavior is known to be absent.** DF-1 stands red under a `fix-the-code`
> decision: the parser ignores the locale's decimal separator. Until that test goes green the
> suite is not green, deliberately.
>
> This statement describes the code at `a1b2c3d`. It is the first closed run against this
> repository, so there is no earlier close-out to measure drift from; the next run will report
> the commit distance since this one, which is the closest thing to a measure of how much of
> the above has gone stale.

Note what it does not contain: no total, no proportion offered as a summary, no sentence that
could be lifted out and quoted as approval of the repository.

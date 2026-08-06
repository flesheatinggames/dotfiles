# The narrative report's fixed section order (R-5.2)

`assemble.py` writes this structure and `trace_report.py` regenerates it and compares. **The
order is not editable per report.** If a section is the wrong shape for something that needs
saying, change it here so every later report inherits the change; a report that improvises its
own structure is one nobody can compare against the last one.

## The order, and why it is this order

A preamble table, then nine sections.

| # | Section | Why here |
|---|---|---|
| — | Preamble | Repository, branch, close date, closing commit, baseline run, commit distance, suite state. Everything needed to know *which* run this is before reading a word of it. |
| 1 | In plain language | First, because the second reader of this report has none of the context and will not survive four sections of vocabulary before reaching anything they can use. |
| 2 | What the suite now asserts | The report's core. Claims by authority, the specified-versus-pinned split, and per claim the asserting tests and the mutation evidence. |
| 3 | Undelivered scope | Immediately after what was delivered, so the two are read together. Separating them is how a partial run comes to read as a complete one. |
| 4 | What this run inherited and did not change | Pre-existing failures and every narrowing, with costs. |
| 5 | Defects, decisions, and applied consequences | Including document-amendment flags and open items carried from earlier runs. |
| 6 | Disputes | After the defects, because a reader who has just read about blocking failures needs to be told immediately that these are not that. |
| 7 | Declared footprint against actual | The measurement planning R-10.3 gates concurrent execution on. |
| 8 | What this run says about the pipeline | Pipeline findings and the R-4.2 consistency checks, which decide how much of everything above can be relied on. |
| 9 | What may now be relied on | The trust statement, last, because it is the only section that depends on all the others. Coverage lives here rather than near the top, and that placement is an argument: coverage is the weakest evidence in the document and putting it first would make it the headline. |

## The prose slots

Nine, one per section. Each is bounded by

```
<!-- PROSE <name> — written by the model, checked by trace_report.py -->
...your paragraphs...
<!-- END PROSE <name> -->
```

Everything outside those markers is generated. `trace_report.py` regenerates the report from
the run record and requires every non-slot byte to match, so text added outside a slot is
reported as an edited generated region. That is strict on purpose: it means a reader can trust
that every table came from the record, without checking.

Within a slot, every numeral is checked against the record's figure set. Identifiers, dates,
requirement numbers, commit hashes, version numbers, fenced blocks, and code spans carrying a
letter or a path separator are all exempt. What is left is a bare numeral in a sentence, and a
bare numeral in a sentence has to come from somewhere.

## What each slot is for

| Slot | Says |
|---|---|
| `executive-layer` | What was verified, what was not, what was found — in ordinary sentences. See `plain-language-brief.md`. |
| `asserted-behavior` | What the claim accounting means. Which behaviors the suite would notice breaking, and which it merely executes. |
| `undelivered-scope` | What is missing and what that leaves unverified. Never netted against what was delivered. |
| `inheritance` | What was already broken, what was excluded, how the run narrowed itself, and what each costs the conclusions. |
| `decisions` | What each answer did to the branch, and for anything still open, what a reader should do and what happens if they do nothing. |
| `disputes` | What the disputes say about the planning that produced them, and what the next plan should start from. |
| `footprint` | What this run contributes to the concurrent-execution question. |
| `pipeline-findings` | Recurring findings first. What the pipeline keeps getting wrong. |
| `trust-statement` | See `trust-statement.md`. The only slot with rules about its shape as well as its content. |

## Writing into a slot

Say what the table above it means. That is the whole job, and it is the job a table cannot do.

Three habits that produce a bad report from good data:

**Restating the table in sentences.** "Six items are done, two failed, and three were skipped"
adds nothing to a table that already says so and consumes the space where the reader needed to
learn that the three skipped ones are all of the input-validation work.

**Netting.** "Most of the plan was delivered" is true and is the sentence that turns a partial
run into a complete-sounding one. R-5.5 forbids it: say which part is missing and why.

**Reaching for a summary judgment.** The pull toward "the suite is now in good shape" is
strong, because it is what a reader wants and because every individual fact supporting it is
true. It is still forbidden, for the reason in `trust-statement.md`.

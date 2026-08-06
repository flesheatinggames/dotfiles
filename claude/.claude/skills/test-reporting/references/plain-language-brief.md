# The plain-language layer, and the one verification pass this stage runs

## Why there is exactly one verifier here

Stage one runs a fresh-context verification pass and it earns its keep — it has caught a bug in
a measuring tool, a fabricated test proposal against files that do not exist, and repeated
mislabeling of estimates as measurements.

Stage two runs none, deliberately, and gives the reason: the deterministic linter checks form
and the human review gate checks substance, so an agent between them re-checks what the owner
is about to check anyway.

That reasoning holds here too, for everything except one property. `trace_report.py` checks
that every number came from the record. The owner checks whether the conclusions are right.
Neither of them, and no amount of care from the author, can check whether the executive layer
is **readable by someone who was never part of this pipeline's design** — because the author
knows what every term means and therefore cannot tell which of them they failed to define. That
is a property only a reader without the context can report on.

So: one agent, one narrow question, on the one section where the author is structurally unable
to be the judge.

## What R-5.3 actually requires

The executive layer must be readable by someone with none of the pipeline's context, and must
still be accurate. Those pull against each other, and the failure modes are on both sides.

**Accurate but unreadable** is the default failure. The vocabulary this pipeline runs on —
claim, cited, pinned, ratified, seam, slice, mutation check, work item, footprint, narrowing,
dispute, defect registry — is all load-bearing and all invented here. A paragraph using four of
those terms is precise and says nothing to the second reader.

**Readable but inaccurate** is the failure that gets past review, because it reads well. It
arrives as generalisation: "the parsing is now tested" for a run that asserted four specific
behaviors of one function, "coverage improved substantially" for a figure the table gives
exactly. Every simplification that drops a bound is this failure.

The rule that resolves the tension: **no pipeline vocabulary without an inline definition, and
no simplification that drops a bound.** Both, in the same sentence, as often as it takes.

## Writing it

Three to six short paragraphs. It answers three questions in order, and it should be possible
to stop reading after any one of them and have learned something true.

1. **What was verified?** Which specific behaviors, and how strongly. Define "mutation check"
   inline the first time — something like *"a check that deliberately breaks the code to
   confirm the test notices"* — because it is the distinction the whole report turns on and it
   is not a term anybody outside this project has met.
2. **What was not?** The areas nobody touched, the work that did not complete, the claims
   nobody confirmed. Named, not counted.
3. **What was found?** Defects and what was decided about each. If the suite is red on purpose,
   say so here rather than leaving the reader to discover it in section 5.

Every number comes from the tables in this document. Small counts are better spelled out —
"four behaviors", not "4 behaviors" — which also keeps the tracer's attention on the numbers
that matter.

Say "this run" rather than "we". The report is a record, not an account of anybody's effort.

## The brief, verbatim

Give this to a fresh-context agent with the executive layer pasted below it, and **nothing
else** — no plan, no report, no repository, no explanation of what the pipeline is. The absence
is the whole method. An agent that has read the rest of the report can no longer tell you which
terms were undefined.

---

You are reading the opening section of a report about the state of a software project's
automated tests. You have no other context and you are not expected to have any. Do not go
looking for any: do not open files, do not search, do not ask what anything is. Your not
knowing is the measurement.

Read it once, at ordinary speed, as someone who owns this project but has never seen this
report format before.

Answer four questions.

1. **Which words or phrases could you not define** from this text alone? List them exactly as
   written. Include any term you could guess at but not state confidently — a guess you would
   not defend is the same as not knowing, and it is the case this check exists to catch.

2. **Which sentences could you not act on?** For each, say what you would need to know to
   decide what to do. A sentence you understood but that left you with no idea what it implies
   for you counts here.

3. **What would you now say this report says**, in three sentences of your own? Do not reuse
   its phrasing.

4. **Is there anything you would want to check before repeating any of it to someone else?**
   Name what and why.

Do not judge the writing, do not suggest improvements, and do not be generous. A term you half
understood is a term you could not define. Report it.

---

## Acting on what comes back

Anything named in answer 1 or 2 **reopens the layer**. Define the term inline or remove it;
rewrite the sentence or cut it.

Answer 3 is the one that catches the second failure mode, and it is the reason the brief asks
for the reader's own words rather than for a verdict. If the summary they produce is more
confident than the layer intended — if bounds have gone missing, if "four behaviors of the
parser" has become "the parser" — then the layer reads as broader than it is, whatever its
sentences literally say. That is not a reading error to correct in the reader. It is the layer
inviting the generalisation, and the layer is what changes.

Answer 4 usually surfaces the sentence that would be quoted out of context. Whatever it names
is worth a bound it does not currently carry.

Record that the pass ran, and record it if it did not. R-9.3: skipped verification appears in
the report with its cost, and the cost here is specific — it means nobody has checked the one
property the author cannot check.

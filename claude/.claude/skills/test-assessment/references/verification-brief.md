# Verification Brief

Pass this text to the verification agent, along with the path to the drafted report and
the path to the repository. Pass **nothing else** — no working context, no reasoning, no
confidence levels, no hints about which findings are shaky. The verifier's independence is
the entire value of the pass, and a leaked opinion destroys it.

---

## Brief to give the verifier

You are verifying a test assessment report that another agent drafted. You have the report
and the repository. You do not have the drafting agent's reasoning, and you should not try
to reconstruct it.

**Your job is not to redo the analysis.** Do not build your own behavioral map, do not
form your own opinion about what the test strategy should be, and do not add findings the
report missed. Your only job is to take the claims the report makes and check whether they
are true against the repository.

### What to check, and how thoroughly

**In full: every finding in the top tier of the risk ranking.** Check each one completely.

**By sample: the remainder.** Take a spread across sections rather than a block from one —
some behavioral map entries, some test quality judgments, some exclusions, some seam
recommendations. Aim for roughly one in four. State what you sampled and how you chose it,
so a reader knows what was and was not checked.

### The specific checks

Every check is a concrete comparison of a claim against evidence. Read the actual file.

1. **Behavioral claims.** The report says a function does something. Read the function.
   Does it actually do that? Watch for claims that are true of the happy path but wrong
   about error handling, edge cases, or early returns.

2. **Test quality judgments.** The report says a test is assertion-free, asserts against
   mocks, restates the implementation, or is an unreviewed snapshot. Read the test. Is
   that accurate? A test with a meaningful assertion the report overlooked is a
   correction. So is a test the report called adequate that in fact asserts nothing.

3. **Seam recommendations.** The report says code has a dependency requiring a seam — a
   database call, a network call, a clock read, an internally constructed collaborator,
   work in a constructor. Read the code. Is that dependency actually there, at the file
   and line given? Is the named seam type the right one from the catalog? Is the paired
   characterization test actually writable at the boundary described?

4. **Untested requirements.** The report says a requirement has no test verifying it.
   Search the test suite yourself. Is there a plausibly matching test the report missed?
   Search by behavior and by the names involved, not only by the requirement's wording.

5. **Exclusions.** The report excludes code with a stated reason. Does the reason hold?
   Check especially: files called generated that have been hand-edited since; boilerplate
   that in fact contains a conditional; accessors that in fact compute something; code
   called dead that is reachable through dynamic dispatch, reflection, string-keyed
   lookup, plugin registration, framework autoloading, or an external consumer.

6. **Numbers.** Do the coverage figures match the coverage output? Do the counts in the
   testability proportions add up? Does the arithmetic in the effective coverage
   calculation work?

7. **Labels.** Is anything stated as measured that is actually inferred or estimated? This
   is the report's most serious possible defect, it has recurred across reports, and it
   deserves a deliberate pass of its own.

   Check **function counts** specifically, not just complexity values. Both come from the
   same token scanner on TypeScript and JavaScript, and both are estimates, but reports
   tend to label the complexity correctly and the counts as "measured". Compare against the
   test runner's own function total — a large divergence (one real case: 338 versus
   Istanbul's 1,106 over the same files) proves the counts are not measurements.

8. **The decisive experiment, where one exists.** If the report claims a test suite would
   fail to catch a specific defect, that is testable rather than arguable. Say so. You must
   not modify the repository yourself, so report it as the check the drafting agent should
   run under a controlled backup-and-restore procedure, and name the exact mutation.

9. **The machine-readable index, if Section 13 is present.** The index is the interface to
   the planning stage, and a wrong index is worse than a missing one because a later stage
   will trust it without reading the prose. Check that it agrees with the report:

   - **Tiers.** For every finding in the index, does its `tier` equal the risk the findings
     table in Section 1 gives that same identifier?
   - **Targets.** Do the `files` on each finding and the `locations` on each recommendation
     actually appear in the prose for that item, and do those paths exist in the repository?
   - **Labels.** Does every `metrics` entry marked `measured` correspond to a number the
     report itself presents as measured? This is check 7 applied to the index, and it is the
     place the two most easily drift apart, because the index is written last.
   - **Contested items.** Does the set of items carrying a non-null `contested` field match
     the contested findings Section 10 lists? An index that quietly settles something the
     prose calls contested is a serious defect.
   - **`safe_to_execute`.** Where the prose says a recommendation is not safe to execute as
     written, does the index say `false`?
   - **Open questions.** For each one, could it have been answered from the evidence? A
     question parked here is escalated to a person by the next stage, so one that reading the
     code or the document would have settled costs somebody a decision they should never have
     been asked for. Check the other direction too: where the report says "either … or" in a
     recommendation and does not choose, is there a corresponding open question, or was a
     choice left dangling with no identifier?

   Do not check the index's schema — `scripts/check_index.py` does that deterministically and
   better. Check only whether the index tells the truth about the report.

### Reporting your findings

For each claim you checked, give one of three verdicts:

- **Confirmed** — the evidence supports the claim. Name the evidence briefly.
- **Corrected** — the evidence contradicts the claim. Quote the evidence and state what
  is actually true.
- **Contested** — the evidence is genuinely ambiguous and could support either reading.
  State both readings and what would settle it.

Use **contested** sparingly and honestly. It is for real ambiguity in the evidence, not
for cases where you did not look hard enough. If you did not check something, say you did
not check it rather than marking it contested.

Return a structured list: the claim, its location in the report, your verdict, and the
evidence. Do not rewrite the report — the drafting agent applies the corrections.

---

## What the drafting agent does with the result

**Resolve every discrepancy by returning to the evidence.** Read the code, the test, or
the document yourself. Do not average the two positions. Do not prefer either agent by
default — not the verifier for being independent, not yourself for having more context.
The evidence decides.

Where the evidence is genuinely ambiguous after you have looked, leave the finding in the
report marked `[contested]` with both readings stated. A contested finding is useful input
to the planning stage; a finding silently dropped because two agents disagreed is a loss.

Then record in the report's Verification section: that the pass ran, what it checked, which
claims were corrected, which are contested, and which portions were verified in full versus
sampled.

If the verification pass could not run at all, the report must say so plainly and is marked
lower confidence.

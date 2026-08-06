# When something fails

R-8.1 to R-8.3. Three rules, and each one is a place where doing the helpful thing is the
wrong thing.

## R-8.1 — Relay the diagnosis verbatim

**A stage failure halts the ratchet. The orchestrator reports the stage's own diagnosis —
verbatim, with its location — and the artifact state it leaves behind. It never summarises a
failure into softer words, never retries a stage on its own initiative, and never patches
around one.**

Verbatim is a rule rather than a style preference, and there are three reasons.

**Every diagnosis in this suite was written to be acted on.** They are not error messages that
happen to be printed near a failure; each one names the file, the line, the rule, and what to do
about it. `check_index.py` on a version mismatch does not say "the index is invalid" — it says
which version it found, which it needs, that this is a backfill rather than a re-assessment,
what to write, and that nothing is re-measured. A summary of that sentence is strictly less
useful than the sentence.

**Softening changes the owner's decision.** "The plan has a few lint problems" and a list of
eleven rules each naming a line are different inputs. The first invites "carry on anyway"; the
second is a work list.

**A paraphrase cannot be checked.** The orchestrator is the one component with no analytical
capability of its own, so when it rewrites another component's output the rewrite has no
authority behind it and nothing in the pipeline compares the two.

This is why `pipeline_state.py` runs the validators as **subprocesses rather than importing and
calling them**. A diagnosis reconstructed from a caught exception is the same text re-worded by
the orchestrator, which is exactly what this rule forbids. Capturing the bytes makes the relay a
copy.

### What to relay

The diagnosis, unedited, plus:

- **Which check produced it**, by script name.
- **The artifact state it leaves behind** — what exists, what does not, and what is half-written.
  A stage that failed part-way leaves a repository in some condition and the owner needs to know
  which.
- **What the pipeline will do when re-invoked**, which is R-8.2: nothing but derive the state
  again and find the run where it stands.

### What never to do

- **Retry.** Not once, not with different arguments. If a stage failed for a reason a retry
  would fix, that is a defect in the stage, and hiding it behind a retry means it is never
  found.
- **Patch around it.** Editing an artifact to make a check pass is forbidden by R-9.1 outright,
  and it is the specific failure the whole suite is built to prevent: a check that passes because
  something was edited to make it pass reports the same green as one that passed honestly.
- **Rank the problems.** Deciding which of eleven lint failures matters is an opinion about the
  artifact, and R-7.2 keeps the orchestrator from having those.

## R-8.2 — Recovery is re-invocation

**The owner addresses the cause, invokes the orchestrator, and state derivation finds the run
where it stands.**

There is no resumption machinery and no recovery mode, because there is nothing to resume from:
the state is in the artifacts, so an interruption costs exactly one re-invocation. The stages'
own designs carry the recoverability — one commit per item, degrade-with-stated-cost, hard stops
that name what to do — and the orchestrator adds none of it and depends on all of it.

The practical consequence: **an orchestrator invocation is never in a hurry.** There is no
in-flight state to preserve, no partial progress to lose, and no reason to push past a stop in
order to avoid starting again.

### The one state it may only relay

`execution-incomplete` — a run started and did not finish — is the position where this rule bites
hardest, because the orchestrator can see the state clearly and still may not act on it.

Resuming an interrupted execution run **is not implemented, deliberately**. Pre-flight stops and
names the two supported ways forward without choosing between them, **because one of them
destroys work**. Choosing on the owner's behalf is forbidden by R-9.2, and it is forbidden for a
reason that is easy to feel and wrong: the orchestrator has just derived the state, it can see
which option is tidier, and offering that reading is a recommendation about a choice with an
irreversible branch in it.

Run pre-flight so the two options are printed in its own words. Add nothing to them.

## R-8.3 — Drift is surfaced, not adjudicated

**The state script compares the commits recorded in the artifacts and flags divergence, and the
affected stage's own revalidation decides what drift costs. The orchestrator's brief states the
flag and the deciding stage.**

Drift means the repository moved between one artifact being written and the next. It is
sometimes harmless and sometimes invalidates half a plan, and **the difference is not visible
from the commit identifiers**. What decides it is the content of the commits against the content
of the artifacts, which is analysis, and the orchestrator does not do analysis.

Each flag therefore names both commits and the stage that will price it:

| Between | Decided by | What that stage does about it |
|---|---|---|
| Assessment commit and plan's `assessment_commit` | test-planning | Its input checks read the assessment the plan declares it was built from |
| Assessment commit and `HEAD` | test-execution | Pre-flight measures commit drift and marks moved targets `stale` |
| Run base commit and `HEAD` | test-reporting | The run record measures base-to-close, not to `HEAD` |

That third row exists because of a real defect worth carrying forward. The R-4.2 commit check
once measured to `HEAD`, so the first ordinary thing the owner did on the branch after
close-out — adding one line to `.gitignore`, which the report had just told them to do — made a
finished record report itself inconsistent. **A closed record describes the run, not the
branch.** The drift flag has to say the same thing, or it will contradict the record it is
describing.

**Never say a drift is harmless.** The correct sentence is "the assessment was written against
`88630f4` and the repository is at `5a5d1fc`; stage three's pre-flight measures what that costs
and marks any work item whose target moved as stale." The owner can act on that. "There has been
some drift but it looks minor" is the orchestrator having an opinion about code it has not read.

## What a failure is not

**A partial run is not a failure.** R-6.5: an execution run that ended partial proceeds to
reporting, with the partiality stated in the brief. Partial-and-honest is a pipeline success
mode, and the reporting stage is built to say exactly which fifth of the work is missing. Sending
a partial run back to be completed first would be the orchestrator deciding that an honest
partial record is not good enough, which is a judgment about scope that belongs to the owner.

**A run that stopped at a gate is not a failure.** Gates are where the pipeline is supposed to
stop. A brief that apologises for reaching one has misunderstood what it is for.

**A red suite at close-out is not necessarily a failure.** A test standing red under a recorded,
owner-facing decision is the pipeline working: it means a real defect was found, verified by a
fresh-context reader, and left visible on purpose. The closing brief says so plainly rather than
reporting the run as broken.

# Composing the two gate briefs

A gate brief is the orchestrator's main product. Everything else it does is invoke a script and
relay what came back; this is the one place it writes something a person reads and acts on.

**The standard the brief is held to.** The owner can act on it without opening the orchestrator
requirements, the plan template, or any stage's `SKILL.md`. That is the acceptance criterion in
Section 11 stated as a test you can apply to a draft: hand it to someone and see whether they
need a second document.

## What a brief always contains

1. **Where the run stands**, in one sentence, without pipeline vocabulary. Not "the position is
   `awaiting-approval`" but "the plan is written and waiting for you".
2. **What must be decided**, item by item.
3. **Where each decision is recorded, and what recording it looks like.** This is the part most
   often left out and the part the requirements name explicitly. A brief saying "resolve the
   escalations" without saying that a resolution is a `resolution` field on the escalation block
   leaves the owner to go and find that out.
4. **How the pipeline verifies it was recorded** — which check will fail, and what it will say,
   if something is missed.
5. **What happens next**, and that nothing happens until the owner acts.

## The sentence a brief may never contain

**The orchestrator's own recommendation.** Not on an escalation, not on a decision, not on a
ratification, not on a defect, not on plan approval, however obvious the answer looks (R-9.2).

A brief **may** restate a recommendation a stage recorded — the plan's `recommendation` field on
an escalation is written by the planner and belongs in the brief. It **may not** add one. And
the restatement must be labelled as the plan's: an unlabelled restatement is indistinguishable
from an addition, and the owner reading it cannot tell whether they are being told what the
planner concluded or what the orchestrator thinks.

This holds even when the plan recorded no recommendation and the answer seems plain. Stage two
already faced this and answered it: whichever side a test asserts gets enshrined, so a decision
that looks obvious to something with no stake in the codebase is exactly the kind that should
be made by someone with one.

**Nor may a brief present a decision so as to make one answer the path of least resistance.**
Ordering, emphasis and length are all ways of recommending without a recommending sentence. Give
each option its own paragraph and its recorded consequence, in the order the plan lists them.

## Gate one

Built from `gate_brief.py --gate 1`, which extracts everything below so the orchestrator does
not have to read the plan (R-7.2).

**Open the brief with scale**, before any detail. A gate one with forty pinned claims says so up
front and estimates the sitting rather than presenting an unbounded list as a small ask
(R-10.3). The script names the scale and the estimate; the estimate is words rather than a
number, deliberately, because a figure here would be a figure nobody computed.

The thresholds come from the two real plans and the planner's own sizing heuristic. `design-os`
came out at 16 claims and `sbcf-app` at 37; the heuristic caps a plan at 8 slices of 8 to 25
claims, so about 200 is the ceiling. A list of 40 is a fifth of the maximum the planner can
produce, and a brief that presents it as a quick read has misdescribed the ask.

Then, in this order:

**Escalations and decisions.** Each with its identifier, what it is about, every option with its
consequence, and — where an option carries one — which work items that answer rewrites. The
rewrite matters to the owner because it tells them the answer changes the shape of the plan
rather than only unblocking it. Then where the resolution is recorded.

Say which class each is, because the three behave differently: a `flagged` item is a note and
never a blocker, an `escalation` is code contradicting a document, and a `decision` is a scope or
approach choice the planner was not authorised to make.

**The ratification list.** Its size, where it lives, and what ratifying looks like. Say that only
pinned claims need ratifying and that cited claims appear for reading rather than deciding.

Say what ratification *means*, because the asymmetry is not obvious and it governs how carefully
the list should be read: **a claim ratified in error becomes a specification.** A test gets
written asserting it, and from then on the behavior has the standing of a requirement because a
passing test says so. The planner already carries the cost one way — it labels a claim `pinned`
when unsure, because being wrong about `pinned` costs a needless decision and being wrong about
`cited` enshrines something nobody agreed to. The owner is the other half of that arrangement.

**The target proposal.** Its axes, what each is measured from and to, and whether each figure is
measured or estimated. Then that `target.approved` and `plan-meta.approved` are separate fields
approving separate things: a coverage number and a plan. **An owner may approve the plan while
deferring the number**, which is exactly what `form: delta-with-rederivation` is for, and a brief
that does not say so invites the owner to think approval is one act.

**The degradations the plan inherited**, each with what it cost this plan. A verification pass
recorded as `skipped` belongs here: it advances the pipeline and it means every finding in the
assessment is single-sourced, so the owner approves the plan knowing no second reader checked
the map it was built from.

**The scope figures.** How many reachable classified functions the plan's claims locate on, out
of how many exist. This is the number that catches a plan that passes every check and plans for
almost nothing, and it belongs in front of the owner rather than in the plan's own prose.

Close with plan approval: where it is recorded, what the block contains, and that **nothing
derives it**. The pipeline stops here until it exists.

## Gate two

Built from `gate_brief.py --gate 2`.

**Point at the sheet; do not re-describe the defects in it.** `docs/test-closeout.md` already
carries each defect with its claim, the claim's source and authority, what the code actually
does, the red test, the fresh-context verification that let the test stand, and the four options
with what each costs. A second rendering of the same defects in the brief would be a second
description of a decision the owner is about to make from the first, and the two would disagree
the moment either changed.

The brief states:

- **How many defects, and how many are answered.** Whether a sheet is complete is judged by
  stage four's own `validate_answers` and never by anything here.
- **That the gate is one sitting.** A partially answered sheet is refused rather than
  half-applied. An owner who cannot finish now should come back to it whole; nothing is lost by
  waiting, because the state is in the artifacts.
- **That consequences are applied on decision** — each answer ends in a transformation of the
  branch, verified through the check runner and committed, rather than in a note.
- **That one option is theirs alone.** `downgrade` makes a real failure stop being visible and
  is available to nobody else at any point in this pipeline. The sheet's validator rejects a
  decider name that looks automated, which is the mechanism, but the brief says the reason.
- **Any disputes**, and that answering them is optional. A dispute is a planner error with
  evidence captured and nothing red on the branch, so leaving one open is a legitimate outcome
  that stays an open ledger item.

**When the gate is empty, say what that means rather than skipping it.** A run that registered
no defects means every claim the plan asserted held against the code as written. That is a real
outcome and worth one sentence. The run still closes by applying the empty sheet, and the brief
says the ratchet is continuing rather than stopping — otherwise the owner is left waiting for a
decision nobody needs to make.

## The closing brief

Not a gate, but the last thing the orchestrator writes, and it has its own obligations.

- **The branch is settled**, and what each close-out decision did to it. `fix-the-code` and
  `accept-with-red` commit nothing and leave a test red; `requirement-wrong` rewrote one test and
  raised a document-amendment flag; `downgrade` wrote a marker naming the defect.
- **What the ledger now holds open**, which is what the next assessment is obliged to confirm,
  update, or contest. This is the only mechanism under which an open defect provably cannot
  vanish between runs, so the owner should know what it is holding.
- **The merge instruction**, handed over rather than executed. **The orchestrator never merges,
  never pushes to a protected branch, and never deploys** (R-9.4).
- **If the suite is red, that it is red on purpose**, which tests, and under whose recorded
  decision. A closing brief that says a run finished without saying the suite has a standing red
  in it has told the owner the wrong thing about their repository.

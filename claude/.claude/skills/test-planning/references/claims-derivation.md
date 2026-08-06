# Claims Derivation — Fan-Out Procedure

R-5.1 says that before any work item is constructed, the planner derives the **claim set**:
for every target above the value line, the behavioral claims its tests must verify, each with
its text, its source, and its label. R-5.2 says that derivation runs as parallel read-only
subagents, one per target area.

This file is the procedure, the verbatim prompt, and the output schema.

## Why once, up front, over the whole scope

R-5.5 requires the whole claim set derived in one pass rather than slice by slice. The reason
is the human gate. The owner ratifies the pinned claims and resolves the escalations in one
review sitting; deriving per slice would mean interrupting them once per slice, and a review
that happens five times is a review that stops happening.

It also makes the merge possible. Two areas that derive the same claim from the same document
statement can only be deduplicated if both derivations exist at once.

## Step 1 — Partition

```bash
python3 <skill>/scripts/partition.py --assessment <path> --repo . --areas 5 --json > /tmp/partition.json
```

Read its `axis_reason`. The script chooses between a per-finding and a per-module split from
the collision counts, and the reason is worth understanding before you send the readers out:
a per-finding split on a repository whose findings overlap heavily sends the same file to
several readers, who derive the same claims independently and leave the merge to sort it out.

Areas larger than the line cap are split by file, so no file ever goes to two readers. That
disjointness is what makes the merge's counts mean anything.

## Step 2 — Spawn the readers

**All in a single message**, so they run concurrently rather than in sequence. Each gets:

- the same prompt below, verbatim;
- **its own disjoint file list** from `partition.json`;
- the behavioral documents the assessment marked usable (R-4.2 — inherit that inventory, do
  not re-discover it);
- the finding titles for its area, so it knows what the assessment already concluded;
- an explicit read-only instruction.

Use `subagent_type: "general-purpose"`.

### Prompt template

> You are deriving BEHAVIORAL CLAIMS for a test plan. Repository: `<absolute path>`.
>
> A **behavioral claim** is a plain-language statement of what a piece of code must be
> verified to do, precise enough that someone could write a test from it without asking you
> anything. "Handles errors correctly" is not a claim. "`parse_amount` raises `ValueError`
> when given an empty string, rather than returning zero" is.
>
> **Your area.** Read these files in full:
> `<file list with line counts>`
>
> **The assessment's findings for this area**, which you may use as context and must not
> re-derive:
> `<finding ids and titles>`
>
> **Behavioral documents.** These are the only documents the assessment found that state
> intended behavior of this code. Do not go looking for others:
> `<document paths, or "none — the assessment found no usable behavioral documents">`
>
> ---
>
> ### What to produce
>
> For every function, method, or exported unit in your files, derive the claims its tests
> must verify. For each claim:
>
> 1. **Text** — one sentence, specific enough to write a test from. Name the input condition
>    and the observable result.
> 2. **Label** — exactly one of:
>    - `cited` — traced to one of the behavioral documents above. Requires the document path,
>      a line or section, **and the document's own words quoted**.
>    - `pinned` — read from the code. Documents what the code currently does, which nobody
>      has ratified as correct. Requires the code location and the line quoted.
>
>    Do not use any other label. `ratified` exists but only ever results from owner review,
>    so it is not yours to assign.
> 3. **Source** — `{kind, location, quote}`. The quote is mandatory for `cited` and expected
>    for `pinned`.
> 4. **Locations** — every `path:line` the claim applies to. Repository-relative, never
>    absolute.
> 5. **Symbols** — the function or method names the claim is about.
>
> ### The label distinction, and which way to err
>
> `cited` means a document says so. `pinned` means the code does it and nobody has said it
> should. A name that reads like a specification is not a specification. A docstring is not a
> requirements document unless the assessment listed it as one. A test asserting something is
> not evidence that anyone decided it was right — that is exactly the circularity this
> distinction exists to break.
>
> **When you are unsure, label it `pinned`.** The two errors are not symmetric. A claim
> wrongly pinned costs the owner one needless approval. A claim wrongly cited skips
> ratification entirely, gets a test written against it, and from then on carries the standing
> of a specified requirement that nobody ever agreed to.
>
> ### Symbols with no claim
>
> Some units genuinely warrant no claim: a trivial pass-through, a private helper whose
> behavior is fully covered by claims on its caller, generated code. Record each in
> `no_claim_reasons` with a reason. **Do not silently skip anything.** A merge step checks
> every symbol you report examining against your claims and your reasons, and an unaccounted
> symbol fails that check.
>
> ### Conflicts
>
> While reading, you will find places where the documents and the code disagree, or where the
> code disagrees with itself. Report each in `conflicts` under exactly one class:
>
> - **`flagged`** — a document specifies behavior and **no code implements it**. Give the
>   document location and quote, and say how you established the code is absent (which
>   searches you ran, not just the conclusion).
> - **`escalation`** — a document specifies behavior and **the code contradicts it**. Give
>   both sides with locations and quotes. Do not decide which is right.
> - **`decision`** — a choice about scope or approach that changes what gets built and is not
>   yours to make. Give the question, the options, and what each costs.
> - **`inconsistent-pinned-pair`** — two pieces of code that duplicate the same logic and
>   behave differently, with no document covering either. Name both symbols. Emit a pinned
>   claim for each describing what it actually does; do not write one claim describing what
>   you think both should do.
>
> ### Rules
>
> - **Read-only.** Do not modify, create, or delete any file.
> - **Do not fabricate.** A claim you cannot source is not emitted. If a file is too tangled
>   to understand well enough to derive claims for, say so in `unreadable` with the reason
>   rather than guessing.
> - **Do not re-derive the assessment.** You are not judging risk, choosing seams, or ranking
>   anything.
> - **Do not plan.** No slices, no ordering, no work items. Claims and conflicts only.
> - **Repository-relative paths only.**
>
> ### Output
>
> Return **only** a JSON object of this shape, and write it to `/tmp/area-<AREA ID>.json`:
>
> ```json
> {
>   "area": "<area id>",
>   "files_read": ["<every file you read, in full>"],
>   "symbols_examined": ["<every function or method you looked at>"],
>   "claims": [
>     {
>       "text": "<one sentence, testable>",
>       "label": "cited | pinned",
>       "source": {"kind": "document | code", "location": "<path:line or path §n>", "quote": "<its own words>"},
>       "locations": ["<path:line>"],
>       "symbols": ["<name>"],
>       "notes": "<optional, only when the claim needs a caveat>"
>     }
>   ],
>   "no_claim_reasons": [{"symbol": "<name>", "file": "<path>", "reason": "<why none>"}],
>   "conflicts": [
>     {
>       "class": "flagged | escalation | decision | inconsistent-pinned-pair",
>       "title": "<short>",
>       "document": {"location": "<path:line>", "quote": "<...>"},
>       "code": {"location": "<path:line>", "quote": "<...>"},
>       "symbols": ["<for inconsistent-pinned-pair, both names>"],
>       "note": "<what makes this a conflict, and what would settle it>"
>     }
>   ],
>   "unreadable": [{"file": "<path>", "reason": "<why you could not derive claims>"}]
> }
> ```

## Step 3 — Merge

```bash
python3 <skill>/scripts/merge_claims.py /tmp/area-*.json --ledger /tmp/partition.json --json
```

Both gates must pass. `merge_claims.py` prints the remedy for each failure; the remedies are
worth restating because both have a tempting wrong answer:

- **Gate A fails** → re-run the reader that came up short, or record the missing reasons.
  The tempting wrong answer is to trim the ledger until it matches what came back, which
  converts a gap into a silence.
- **Gate B fails** → raise the value line, re-partition, and record the narrower scope in the
  plan's exclusions. The tempting wrong answer is to drop the claims that fit least
  comfortably, which is scope reduction without anybody deciding it.

## Step 4 — Spot-check before you build on it

The merge is arithmetic; it cannot tell you whether a claim is true. Before writing work
items, check by hand:

- **Every `cited` claim.** Open the document at the location given and confirm the quote is
  there and says what the claim says it says. This is the check the owner cannot make cheaply
  and it is where a wrong label does the most damage.
- **The claims that will land in the top-tier slices.** Read the code at their locations.
- **Anything two readers derived independently.** Convergence is evidence — the readers had no
  contact beyond the prompt — but check that they really mean the same thing before the merge
  collapses them into one claim.
- **Every `possible_duplicates` group.** These are claims citing the same document passage with
  different wording. The merge deliberately does not collapse them, because one section often
  holds two requirements. Decide which it is.

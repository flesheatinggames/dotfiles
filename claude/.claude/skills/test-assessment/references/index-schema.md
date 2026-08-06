# Machine-Readable Index — Normative Field Reference

The report's last numbered section — 14 when a reconciliation section precedes it, 13 when
none does — is a single fenced block whose info string is exactly
`json assessment-index`. It carries stable identifiers for everything a later stage needs
to reference, and nothing that is not already stated in the report's prose.

The index exists because the planning stage must be able to point at a finding and know
that the pointer survives a correction. Positional numbering does not survive: the
verification pass in one real run corrected nineteen claims, and any correction that
merges or splits a finding renumbers everything below it.

**One file, two audiences.** The index does not duplicate the report's reasoning; it
duplicates only the identifiers, the classifications, and the numbers. The same reasoning
that fixes R-7.2's section order — that paired files drift apart — is why the index lives
inside the report rather than beside it.

**The index is written after the verification pass**, never before. Verification applies
corrections, and an index written before it describes a report that no longer exists.

**Emit exactly one such block per report.** `check_index.py` fails a report containing two.

---

## Identifier scheme

Every referenceable thing in the report carries an identifier matching one of these
patterns. Identifiers are unique within a report and stable across revisions of it: once
`F3` names a finding, a later revision either keeps `F3` on that finding or retires the
identifier. Renumbering is prohibited, because it silently redirects every reference made
by a downstream stage.

| Prefix | Pattern | Names |
|---|---|---|
| `F` | `^F[0-9]+$` | A risk-ranked finding |
| `R` | `^R[0-9]+$` | A recommendation, whether or not it is a catalog seam |
| `X` | `^X[0-9]+$` | An exclusion |
| `D` | `^D[0-9]+$` | A degradation |
| `Q` | `^Q[0-9]+$` | An open question the assessment identified but did not answer |

Identifiers are assigned in the order the report presents the items, which makes the first
assignment readable. They are not re-derived afterwards.

**Retiring an identifier.** When a correction removes a finding entirely, drop it from the
index and do not reuse its number. When a correction splits one finding into two, the
original identifier stays on whichever half retains the original claim, and the other half
gets a fresh number at the end of the sequence.

---

## Top-level shape

```json
{
  "index_version": "1.2",
  "repository": "<name>",
  "report_path": "docs/test-assessment.md",
  "generated": "<YYYY-MM-DD>",
  "commit": "<sha or null>",
  "mode": "requirements-informed | requirements-informed-partial | inference",
  "verification": "passed | passed-with-corrections | skipped",
  "findings": [ ... ],
  "recommendations": [ ... ],
  "exclusions": [ ... ],
  "degradations": [ ... ],
  "open_questions": [ ... ],
  "dependencies": [ ... ],
  "coverage_baseline": { ... },
  "metrics": [ ... ],
  "testability": [ ... ],
  "testability_scope": { ... },
  "reconciliation": [ ... ]
}
```

`reconciliation` is the one optional key, and it is present exactly when the repository has a
run ledger. Every other key is required.

Every key above is required. A list with no members is written as `[]`, never omitted —
an absent key and an empty list are different facts, and a consumer cannot tell an
omission from a genuine zero.

`index_version` is `"1.2"` for this schema. A consumer that does not recognise the version
must refuse to proceed rather than guess at the fields.

**Version 1.0 is the same schema without `testability` and `testability_scope`.** A 1.0
index is not malformed; it was written before those keys existed. A consumer that needs
them — the planning stage's claim-enablement rule is the only one so far — must route a 1.0
index to the backfill instruction rather than reject it on version, because the two
situations have different remedies. A malformed index is re-emitted; an older one is topped
up, which is Step 6 of the procedure run against a report whose analysis is already done.

**Version 1.1 is the same schema without `reconciliation`.** It predates the run ledger, and
it is routed the same way and for the same reason. The backfill is bounded: if the repository
has no `docs/test-ledger.json`, set the version and change nothing else; if it has one, add one
`reconciliation` entry per open ledger item and the matching prose section. Nothing is
re-measured either way.

---

## `findings`

One entry per row of the risk-ranked findings table in Section 1.

```json
{
  "id": "F1",
  "rank": 1,
  "title": "<the finding, as the table states it>",
  "tier": "top",
  "basis": "<the table's basis column, verbatim>",
  "files": ["src/lib/product-loader.ts"],
  "contested": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Matches `^F[0-9]+$` |
| `rank` | integer | yes | The finding's position in the risk ranking, starting at 1. Distinct within the report |
| `title` | string | yes | The finding as the prose states it. Not a paraphrase |
| `tier` | string | yes | One of `top`, `high`, `medium`, `low`. Must equal the tier the prose table gives |
| `basis` | string | yes | What the finding rests on, copied from the table's basis column |
| `files` | list of string | yes | Repository-relative paths the finding concerns. May be empty when the finding is about configuration or about the absence of something |
| `contested` | object or null | yes | `null` when the verification pass settled the claim. Otherwise the object below |

The `contested` object, when present:

```json
{
  "readings": ["<first reading>", "<second reading>"],
  "settled_by": "<what evidence would settle it>"
}
```

At least two readings are required, because a contested finding with one reading is not
contested. The planning stage may not build work on a contested finding without either
resolving it against the evidence or escalating it to the owner.

---

## `recommendations`

One entry per recommendation in Section 9.

```json
{
  "id": "R2",
  "title": "Pass glob results into the loaders instead of capturing them at module scope",
  "kind": "seam",
  "seam_type": 2,
  "locations": ["src/lib/product-loader.ts:11", "src/lib/product-loader.ts:18"],
  "size": "medium",
  "addresses": ["F1"],
  "characterization_required": true,
  "characterization_boundary": "loadProductData() and the twelve has* functions",
  "characterization_note": "<the known-imprecision paragraph, condensed to one sentence>",
  "safe_to_execute": false,
  "independent": false,
  "contested": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Matches `^R[0-9]+$` |
| `title` | string | yes | The recommendation heading |
| `kind` | string | yes | See the closed list below |
| `seam_type` | integer or null | yes | `1`–`4` from the closed seam catalog when `kind` is `seam`; `null` otherwise |
| `locations` | list of string | yes | `path:line` entries. Repository-relative. At least one |
| `size` | string | yes | One of `small`, `medium`, `large` |
| `addresses` | list of string | yes | Finding identifiers this recommendation responds to. May be empty when the recommendation stands alone |
| `characterization_required` | boolean | yes | Whether a characterization test must be written before the change |
| `characterization_boundary` | string or null | yes | The boundary named in the report. `null` when no characterization is required |
| `characterization_note` | string or null | yes | The known imprecision, condensed. `null` when no characterization is required |
| `safe_to_execute` | boolean | yes | `false` when the report says the recommendation is not safe as written — typically because its characterization test cannot pin down enough. A `false` here obliges the planner to escalate rather than schedule |
| `independent` | boolean | yes | See below |
| `contested` | object or null | yes | Same shape as on findings |

**`independent` means independent of the other recommendations**, which is how the reports
already use the word: "R3 is independent of all of the above." Set it `true` when no
dependency edge in this index connects this recommendation to another recommendation, in
either direction. Edges to findings and to open questions do not affect it — a
recommendation blocked only on an owner's decision is still independent of the other
recommendations, and that is a useful thing for the planner to know separately.

`check_index.py` enforces the definition, so the flag and the edges cannot disagree.

**`kind` is a closed list.** Stage one emits recommendations that are not seams — the
seam catalog is closed for seams, not for recommendations — and the planner needs to tell
them apart without reading the prose.

| Value | Means |
|---|---|
| `seam` | A catalog seam refactoring of production code. `seam_type` is required |
| `test-infrastructure` | A change to test scaffolding: mocks, helpers, fixtures |
| `test-repair` | A change to existing tests: adding assertions, deleting placeholders |
| `configuration` | A change to test or coverage configuration |
| `deletion` | Removing dead code, or removing tests that verify nothing |
| `documentation` | A change to a requirements or specification document |
| `other` | Anything else. Requires a `kind_note` field stating what it is |

---

## `exclusions`

One entry per row of the Section 4 exclusions table.

```json
{
  "id": "X1",
  "paths": ["src/components/ui/**"],
  "category": "B",
  "reason": "<the table's reason, condensed to one or two sentences>",
  "units": 66,
  "unit_kind": "functions",
  "belongs_in_tool_config": true,
  "verification_limit": "Could not diff against the upstream shadcn registry",
  "contested": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Matches `^X[0-9]+$` |
| `paths` | list of string | yes | Paths or globs, repository-relative. At least one. A table row naming several files becomes one exclusion with several paths, so the index keeps the report's own grouping |
| `category` | string or null | yes | One of `A`–`F` from the exclusion catalog, or `null` for a row the catalog does not cover, such as test code itself. Where a row cites two categories, record the primary one here and keep both in `reason` |
| `reason` | string | yes | Never empty. An exclusion without a reason is indistinguishable from hiding a problem |
| `units` | integer or null | yes | The count the table gives, or `null` when the table gives none |
| `unit_kind` | string or null | yes | What `units` counts: `functions`, `statements`, `lines`, or `files`. `null` when `units` is `null` |
| `belongs_in_tool_config` | boolean | yes | Whether the report says this exclusion should move into the coverage tool's own configuration |
| `verification_limit` | string or null | yes | Any stated limit on how the exclusion was checked |
| `contested` | object or null | yes | Same shape as on findings |

---

## `degradations`

One entry per row of the Section 11 degradations table.

```json
{
  "id": "D1",
  "degradation": "No test suite exists",
  "effect": "No coverage measured; verification status is uniform across all files"
}
```

All three fields are required. The planning stage inherits every degradation and must
state what each one costs the plan, so both halves of the row must survive into the index.

---

## `open_questions`

A question the assessment identified and did not answer, because answering it requires
weighing risk, scope, or intent. Stage one names these; it does not resolve them.

```json
{
  "id": "Q1",
  "question": "Should the global 80% coverage threshold be lowered or scoped when collectCoverageFrom is set?",
  "raised_by": ["R2"],
  "why_unanswered": "Choosing between lowering the threshold and scoping it is a policy decision about what the build should enforce"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Matches `^Q[0-9]+$` |
| `question` | string | yes | Phrased as a question |
| `raised_by` | list of string | yes | Identifiers of the findings or recommendations that raise it. At least one |
| `why_unanswered` | string | yes | Why stage one did not answer it |

**Open questions exist so that dependency edges have stable endpoints.** Before they
existed, a report could state that a recommendation "must land together with the threshold
decision" and leave the planner with a free-text endpoint it could not resolve. An open
question turns that endpoint into an identifier. It is not a licence for stage one to plan
— a question that stage one *can* answer from the evidence must be answered in the prose,
not deferred here.

---

## `dependencies`

The edges between findings, recommendations, and open questions that the report states as
facts in Section 1. These constrain any sequence without prescribing one.

```json
{
  "from": "R2",
  "to": "R4",
  "type": "partially-blocks",
  "note": "R4's progress is invisible until R2 instruments the file"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `from` | string | yes | An identifier defined elsewhere in this index |
| `to` | string | yes | An identifier defined elsewhere in this index. Must differ from `from` |
| `type` | string | yes | One of `blocks`, `partially-blocks`, `precedes`, `must-land-together` |
| `note` | string | yes | One sentence stating the fact the edge encodes |

| Type | Means |
|---|---|
| `blocks` | `to` cannot be executed at all until `from` is done |
| `partially-blocks` | `to` can be executed, but part of what it should verify is unreachable until `from` is done |
| `precedes` | `to` is best done after `from`, and doing it first creates rework rather than making it impossible |
| `must-land-together` | Applying either without the other breaks something. Order between them is not the point; atomicity is |

**Independence is a node property, not an edge.** A recommendation with no prerequisites
carries `"independent": true`. Writing an edge that asserts the absence of an edge would
make the graph unreadable.

Edges of type `blocks` and `precedes` must form a directed acyclic graph. `check_index.py`
enforces this. `must-land-together` is symmetric in meaning, so record it once, in either
direction, and do not include the mirror edge.

---

## `coverage_baseline`

The per-file coverage figures the report recorded, so the planning stage can state a
coverage delta as a completion check without re-running anything.

```json
{
  "available": true,
  "tool": "Istanbul via next/jest",
  "command": "npx jest --coverage --coverageReporters=lcov --ci",
  "config_in_effect": "coverageThreshold global 80/75/80/80; ./lib/actions/**/*.ts 100/100/100/100",
  "scope_caveat": "collectCoverageFrom is absent, so only files a test imports are instrumented",
  "overall": {"lines": 94.95, "branches": 90.49, "functions": 88.87, "statements": 94.48},
  "files": [
    {"path": "components/label-printing/LabelPrintModal.tsx", "lines": 11.76, "branches": null, "functions": null}
  ],
  "files_complete": false,
  "intended_denominator": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `available` | boolean | yes | `false` when no suite ran |
| `reason` | string | when `available` is `false` | Why there is no baseline |
| `tool`, `command`, `config_in_effect` | string or null | yes | From the provenance section |
| `scope_caveat` | string or null | yes | Anything that makes the numbers narrower than they look |
| `overall` | object or null | yes | Percentages as numbers, not strings. `null` when unavailable |
| `files` | list | yes | Per-file percentages the report states. `[]` when none |
| `files_complete` | boolean | yes | Whether `files` covers every instrumented file, or only the ones the report chose to name |
| `intended_denominator` | object or null | yes | When no coverage exists, the denominator a future measurement should use: `{"unit": "functions", "count": 90}` |

**`files_complete` matters more than it looks.** A report that names only its four
worst-covered files gives the planner a partial list. A planner that treats a partial list
as complete will propose a coverage delta against a baseline of zero for files that are in
fact well covered. Setting this flag honestly is the difference.

---

## `metrics`

The report's headline numbers, each carrying whether it is a measurement or an estimate.
The planning stage derives its target from these, and a target derived from an estimate
labelled as a measurement is a target nobody can hold anyone to.

```json
{"name": "production_functions", "value": 3178, "basis": "measured",
 "note": "TypeScript compiler parser against installed typescript 5.9.3",
 "superseded": [1042]}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Lowercase with underscores. Free-form, but reuse the conventional names below where they apply |
| `value` | number | yes | |
| `basis` | string | yes | `measured` or `estimated`. Nothing else |
| `note` | string | yes | How it was produced. This is what makes `basis` checkable |
| `superseded` | list of number | no | Values this figure previously held, which must no longer appear anywhere in the prose |

**Every figure comes from `figures.py`, and `superseded` is how a recomputation is
enforced rather than remembered.** The script consolidates the analysers' outputs into this
list, and on a re-run it reads the report's existing index and records any figure whose
value changed. `check_index.py` then checks both directions: every current value appears
somewhere in the prose, and no superseded value does.

The failure this catches happened: one report retained token-scanner figures in its
recommendation prose after an analyser correction recomputed every figure in its tables, so
the report stated two different function counts and only the tables were right. Two copies
of a number drift, and the copy in prose is the one a reader quotes.

**Superseded values are checked by size, because small integers collide with ordinary
text.** A superseded value with three or more digits, or a decimal point, fails the report.
A smaller one is reported as an advisory: a figure that fell from `4` to `3` cannot be
distinguished from the word "4" in a sentence about something else, and a check that fires
on every such coincidence would be turned off.

Conventional names, used where the report has the figure:
`production_files`, `production_functions`, `production_complexity`,
`instrumented_files`, `instrumented_functions`, `meaningful_functions`,
`excluded_functions`, `test_files`, `test_cases`, `weak_test_cases`,
`skipped_test_cases`.

**`basis` is copied from the report's own label audit, not re-decided here.** Step 7b of
the procedure already forced every number to be marked measured or estimated. The index
carries that decision forward; it does not make a new one.

---

## `testability`

The testability classification of Section 8, recorded one entry per **function** rather
than only as the proportions the prose states. This is the input the planning stage's
claim-enablement rule consumes: a planner resolves a claim's `path:line` location to an
entry here and learns whether the claim's target is reachable, and if not, what has to
happen first. Without it the planner can only assume reachability, which is how a plan
comes to assert claims through an extraction that no work item performs.

```json
{
  "file": "src/lib/product-loader.ts",
  "function": "loadProductData",
  "line": 24,
  "end_line": 58,
  "category": "needs-seam",
  "seam_type": 2,
  "seam_ref": "R2",
  "note": "Captures the glob result at module scope, so a test cannot supply one"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | string | yes | Repository-relative path |
| `function` | string | yes | The function's name as the source declares it. For an anonymous default export, the name `complexity.py` reported |
| `line` | integer | yes | First line of the function, as `complexity.py` reports it |
| `end_line` | integer | yes | Last line. Must be greater than or equal to `line` |
| `category` | string | yes | One of the four below. Closed set |
| `seam_type` | integer or null | yes | `1`–`4` when `category` is `needs-seam`; `null` otherwise |
| `seam_ref` | string or null | yes | The `R`-number of the recommendation that makes this function reachable. Required when `category` is `needs-seam` or `export-only`; `null` otherwise |
| `note` | string or null | yes | One sentence on why, where the category is not self-evident |

**The line range comes from the analyser, not from reading.** `complexity.py` emits
`name`, `line`, and `end_line` for every function it finds, under `files[].functions[]`, so
a claim's `path:line` resolves to exactly one entry deterministically. Do not hand-write
these numbers; a range that is off by two silently stops resolving.

Two entries may start on the same line — a chained `xs.filter(...).map(...)` is two
callbacks on one line and a real parser reports both — but they may not **disagree about the
category**. A location resolving to two different categories has no category, and the
planner's answer would depend on which entry it happened to pick. Ranges may otherwise
overlap freely, which is what nesting produces.

### The five categories

| Value | Means | What the planner does with it |
|---|---|---|
| `testable-as-is` | A test can reach and drive this function today | Asserts claims against it directly |
| `export-only` | Already pure and already separated; only the missing `export` keeps a test out | Requires the export recommendation to run first, and nothing more |
| `needs-seam` | A catalog seam must land before a unit test can reach it | Requires the seam item in the asserting item's dependency closure |
| `integration-only` | No catalog seam fits; the code is reachable only by integration-style tests | Plans no unit-test claims against it |
| `excluded` | Section 4 excludes this code from the suite | Plans no claims against it at all |

**`integration-only` is where the closed seam catalog deliberately leaves code.** The
catalog is closed at four seam types and the skill is required to say so when none fits,
rather than invent a fifth. That verdict has to be recordable: forcing such a function into
`needs-seam` would make the planner read it as "reachable once a seam lands" when no seam
is coming, and `excluded` would claim Section 4 excluded code Section 4 says nothing about.
Neither is true, and the enablement rule would hard-stop forever asking for a
classification that cannot be written.

`export-only` is a category rather than a flavour of `needs-seam` because the two cost
different things and carry different risk. The export is a one-token edit that moves no
logic and needs no characterization test; a seam restructures code and does. Collapsing
them would make the planner size and guard both the same way, and the seam catalog's
minimal form exists precisely because that is wrong.

An `excluded` entry's `file` must fall under the paths of some exclusion this index
defines. An entry excluded from testing by nothing recorded is an exclusion made in the
index and nowhere else, which is the failure the prose cross-check exists to prevent.

---

## `testability_scope`

What bounds the list above, recorded so a consumer can tell a deliberate boundary from a
gap. Classifying every function in a repository with several thousand of them is neither
affordable nor useful, and it contradicts the map-granularity rule directly.

```json
{
  "tiers": ["top", "high"],
  "recommendation_locations": ["R1", "R2", "R3"],
  "map_granularity": {
    "top": "per-function",
    "high": "public-interface",
    "medium": "module-summary",
    "low": "one-line"
  },
  "complete": false,
  "classified_functions": 47,
  "total_functions": 3178,
  "note": "Top and high tiers plus every function named in a recommendation's locations"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `tiers` | list of string | yes | Which risk tiers were classified exhaustively. Values from `top`, `high`, `medium`, `low`. At least one |
| `recommendation_locations` | list of string | yes | `R`-numbers whose locations were pulled in regardless of tier. `[]` when none were |
| `map_granularity` | object | yes | Tier to granularity, matching the behavioral map's granularity table. Values from `per-function`, `public-interface`, `module-summary`, `one-line`, `omitted` |
| `complete` | boolean | yes | `true` only when the classified set is every function in the repository |
| `classified_functions` | integer | yes | Must equal the number of entries in `testability` |
| `total_functions` | integer or null | yes | The repository's function inventory, from the metrics. `null` where no count exists |
| `note` | string | yes | The scope rule in one sentence |

**`complete` is what the planner checks before it assumes.** With `complete: true` a claim
that resolves to no entry is a claim against something that is not a function, which is a
planning error. With `complete: false` it means the function sits outside the classified
set, and the remedy is a narrow backfill naming that function — not a re-run and not a
guess. The two are different failures and the flag is what tells them apart.

**The standard scope rule**, and the default unless the report says otherwise: every
function in the `top` and `high` tiers, plus every function named in any recommendation's
`locations`, whatever tier it sits in. A ninety-function repository can and should be
classified exhaustively, with `complete: true` and every tier listed.

---

## `reconciliation`

**Optional, and present exactly when the repository has a run ledger.** A first assessment has
nothing to reconcile and omits the key entirely; `check_index.py --ledger` requires it and
requires it to be complete.

```json
"reconciliation": [
  {
    "item": "DF-1",
    "kind": "defect",
    "disposition": "confirmed",
    "evidence": "ledger/money.py:12 is byte-identical to the version DF-1 was raised against; the red test still fails for the same reason."
  }
]
```

| Field | Required | Meaning |
|---|---|---|
| `item` | yes | The open item's identifier, exactly as `ledger.py --open` prints it: `DF-n`, `PF-nn`, `DA-n`, a claim id for a dispute, or a work-item id for undelivered scope |
| `kind` | no | The ledger's kind, carried for readability; the identifier alone resolves it |
| `disposition` | yes | `confirmed`, `updated`, or `contested`. There is no fourth and in particular no `investigating` — an item nobody has looked at is `confirmed`, and writing that down is the point |
| `evidence` | yes | At least twenty characters of what was actually looked at |

**`confirmed` needs its evidence most rather than least.** It is the disposition that costs
nothing to write and asserts the most: that somebody looked and the item is still true. An
unevidenced `confirmed` is indistinguishable from not having looked, which is the exact state
R-7.2 exists to make visible.

The entries mirror the prose section of the same name. `check_index.py --ledger` reads this
array; a human reads the prose; neither is derived from the other, and the report is expected
to say the same thing in both, as it is for every other section.

---

## What the index must not contain

- **Anything the prose does not state**, with one deliberate exception, below. The index is
  a projection of the report, not an additional analysis. `check_index.py` cross-checks
  every identifier against the prose for exactly this reason.

  **The exception is `testability`.** Its per-function entries are a machine interface, and
  restating forty-seven function names in prose would bury Section 8's actual finding — the
  proportions — under a table nobody reads. The compensating rule keeps the discipline
  intact rather than waiving it: the prose states the count and share in each category and
  the scope rule that produced the set, and `check_index.py` recomputes both from the
  entries and fails the report on a mismatch. A projection that no longer projects is what
  the cross-check exists to catch, and this substitutes one mechanical check for another
  rather than removing it.
- **Sequencing.** Stage one classifies the path and states dependencies; it does not order
  the work. There is no `order` field and there will not be one.
- **A value line.** Where to stop is the planner's judgment, informed by the tiers.
- **Numbers that appear nowhere in the report.** If a figure is worth putting in the
  index, it is worth stating in the prose where a reader can see its basis.

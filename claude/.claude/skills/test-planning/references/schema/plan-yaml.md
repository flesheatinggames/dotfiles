# The Plan's YAML Subset, Normatively

The plan is a Markdown file containing fenced YAML blocks. `scripts/planlib.py` parses
those blocks with a bundled parser that accepts a deliberately small subset of YAML. This
document is the definition of that subset.

## Why a subset, and why a bundled parser

**PyYAML is not in the standard library.** This stage and the assessment stage both forbid
installing anything, and the remedy for PyYAML's absence is exactly the `pip install` they
forbid. A linter that cannot run is worse than no linter, because requirement R-11.1 says
the owner never sees a plan that failed lint — so a plan that was never linted arrives
looking identical to one that passed.

Where PyYAML *is* importable, `planlib.py` parses every block both ways and reports a
disagreement as a lint failure. The bundled parser is therefore held to a real
implementation's behavior rather than trusted on its own.

**The subset also buys line spans.** The parser records the file line of every key. Stage
three writes execution status back into this same file (R-7.3), and it must rewrite one
`status:` line without disturbing the comments the owner wrote at review. A parser that
returns only values cannot do that; a round trip through a YAML emitter would reformat the
file and lose them.

## What is accepted

| Construct | Example |
|---|---|
| Block mapping | `id: WI-03` |
| Block sequence | `- WI-01` on its own line |
| Sequence of mappings | `- kind: tests-pass` then further keys indented to the `k` |
| Nested blocks | any depth, indented consistently |
| Literal block scalar | `text: \|`, with `\|-` and `\|+` chomping |
| Folded block scalar | `text: >`, with `>-` and `>+` |
| Double-quoted string | `"with \n escapes"` |
| Single-quoted string | `'with '' doubling'` |
| Plain scalar | `unit-tests` |
| `null` | `null`, `~`, or an empty value |
| Booleans | `true`, `false` — lower case only |
| Integers and floats | `42`, `-3`, `2.5`, `1e3` |
| Comments | whole-line `#` and trailing ` #` outside quotes |
| Empty collections | `[]` and `{}` — the one flow construct permitted, because block style cannot express them |

Indentation is spaces only. A sequence may sit at its key's own column or be indented; a
nested mapping must be indented.

## What is rejected, and why

Each of these raises a parse error naming the line.

| Rejected | Why |
|---|---|
| Anchors `&name` and aliases `*name` | A value defined once and used elsewhere makes the plan unreadable at the point of use, and the owner reviews this file by reading it |
| Tags `!!str`, `!Custom` | Type coercion the reader cannot see |
| Directives `%YAML` | Unnecessary |
| Non-empty flow collections `[a, b]`, `{k: v}` | Line spans stop being meaningful, so status writeback and per-field error messages both degrade |
| Document markers `---`, `...` | One block, one document |
| Complex keys `? key` | Never needed |
| Tabs in indentation | Alignment in one editor, a parse error in every parser |
| Duplicate keys in one mapping | Silently discards one of them |
| `yes`, `no`, `on`, `off`, `y`, `n` as bare scalars | YAML 1.1 reads them as booleans and YAML 1.2 as strings. The subset refuses to pick a side and asks for quotes. A field named for a country code is the classic casualty |
| The same words as bare **keys** | Same resolver, worse failure. PyYAML turns `on:` into the key `True`, so a mapping with an `on` field parses differently in the two parsers and the cross-check reports a whole-block disagreement rather than the one-word problem it is. Rename the field — `date` reads better than `on` anyway. Quoting the key works and is worse, because the quotes become load-bearing and the next person to tidy them away breaks the plan |
| `True`, `TRUE`, `Null`, `NULL` | Same reason, in the other direction. Lower case only |
| A plain scalar continued on the next line | Ambiguous where it ends. Use a block scalar |

## Block info strings

Each fenced block declares its type in its info string: `yaml work-item`,
`yaml claim`, and so on. The linter reads the type from there, so a block with a bare
` ```yaml ` info string is ignored entirely — which is how the plan's own prose can show an
example without the linter trying to validate it.

| Info string | Count per plan | Holds |
|---|---|---|
| `yaml plan-meta` | exactly 1 | Version, repository, assessment path and commit, value line, inherited degradations, resolutions of assessment problems |
| `yaml escalation` | 0 or more | A document-versus-code conflict |
| `yaml decision` | 0 or more | A scope or approach choice the planner is not authorized to make |
| `yaml flagged` | 0 or more | Documented behavior with no implementing code |
| `yaml exclusion` | 0 or more | Something the plan declares it will not do |
| `yaml target` | exactly 1 | The target proposal |
| `yaml claim` | 0 or more | One behavioral claim, defined once |
| `yaml slice` | 1 or more | A slice header |
| `yaml work-item` | 1 or more | A work item |
| `yaml wave-schedule` | exactly 1 | The computed wave schedule |
| `yaml backlog-item` | 0 or more | Optional backlog beyond the target |

An info string beginning with `yaml ` and naming anything else is a lint failure rather
than something to ignore, because a misspelled block type would otherwise vanish silently
and take its work item with it.

## Unrecognised fields are errors

The validator rejects a field it does not know, rather than ignoring it. A misspelled
`justifcation` that is silently ignored produces a plan that lints clean while missing the
justification a deviation requires. The cost of the strictness is having to add a field to
the schema before using it, which is the right cost.

## Claims are defined once and referenced by identifier

A work item carries `claims: [C4, C5]`, not the claim text. Every claim is defined once, in
its own `yaml claim` block in the ratification list.

This matters for three separate reasons. The owner ratifies each pinned claim in one place
rather than once per item that mentions it. Relabelling an approved claim from `pinned` to
`ratified` is a one-line edit that cannot leave a stale copy behind. And a seam item that
merely *enables* a claim can say so with `claims-enabled` without the claim being counted
twice on the ratification list — which was the double-counting problem in the first
version of R-7.1.

## Reading spans from a parsed block

```python
import planlib

by_kind, problems, text = planlib.load_plan("docs/test-plan.md")
item = by_kind["work-item"][0].node
item.line_of("status")      # the absolute file line the `status:` key sits on
item.value_spans["claims"]  # (first_line, last_line) of the claims list
```

`line_of` is what stage three rewrites status with: read the line, replace the value after
the colon, write the file back. Everything else in the file, including the owner's
comments, is untouched.

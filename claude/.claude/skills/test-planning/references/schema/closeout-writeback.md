# What the close-out stage writes, and the order the rules force

The counterpart to `execution-writeback.md`, one stage later. Stage four writes four new block
types into the plan, and they live in this skill's schema for the reason stage three's do:
`plan_lint.py` is the gate, so a block the linter does not know is a block that cannot be
written.

The full field reference for each is in `planlib.py` beside the schema itself. What belongs
here is the part that is not obvious from the fields: **which writes must precede which**, and
the one case where no order works.

## The four blocks

| Block | Holds |
|---|---|
| `close-out` | One decision per defect registry entry: the option, the decider, the date, the rationale, what it left the red test as, the consequence commit, and the check-runner outcomes that verified it |
| `dispute-decision` | R-6.5's optional answer on an impeached pinned claim. Absent is a legitimate outcome |
| `pipeline-finding` | R-8.1's five-category taxonomy, numbered against the run ledger |
| `run-record` | Stage four's extension of the run summary, and the single source for every figure the narrative report states |

All four are refused at the three earlier phases by `premature-closeout-block`, exactly as the
execution blocks are refused at the two before that.

## The phase gate, in both directions

At `--phase executed` a defect's `resolution` must be **null**, and
`defect-answered-before-closeout` says so. That rule matters more than its mirror at the closed
phase: a registry entry is a question put to the owner, and a question that arrives with an
answer already in it was never put to anybody.

At `--phase closed` every defect must carry a resolution, exactly one `close-out` block must
name it, and the two must agree about which option was taken.

## Where no order works

Two pairs of rules are mirror images, and each pair is checked in both directions:

* a `requirement-wrong` decision whose claim is not relabelled `ratified-as-observed` fails,
  and a claim relabelled with no decision behind it fails;
* a run record listing a finding the plan does not hold fails, and a finding block the record
  does not list fails.

Every ordinary write is linted alone and rolled back if it introduces a failure, so whichever
half of a pair went first would introduce the other's failure and be rolled back. Both rules in
each pair are worth having — the first direction catches an overstated suite, the second
catches an unrecorded downgrade of a cited claim's authority — so the writer grew
`planio.Plan.transaction()`, which checks a group of writes as one and rolls the group back
together. Nothing about the rules is relaxed; the group is linted exactly as a single write is.

## The order for everything else

1. The claim's relabelling and the `close-out` block and the defect's `resolution`, as one
   transaction, per decision.
2. The `dispute-decision` blocks, which depend on nothing.
3. The `pipeline-finding` blocks together with the run record's finding list, as one
   transaction.
4. The `run-record` block, last, because it is derived from all of the above and the linter
   recomputes its item, claim, defect, dispute, decision, finding, and amendment lists against
   them.

The run record's claim list is the one section that is **recomputed rather than copied forward**
from the run summary. R-4.1 forbids re-deriving a figure stage three measured; a claim's label
is not a figure, and stage four changes it. Copying it forward would make the report's central
table describe a state that stopped existing at the close-out gate.

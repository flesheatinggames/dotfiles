# Parallel Test Reading (Fan-Out)

How to honour "read every test, no sampling" on a suite too large for one context.

Requirement R-6.2.1 forbids sampling. Its stated justification — that target repositories
have few tests, so exhaustive reading is affordable — does not hold on a mature suite. A
real case: 37 files, 22,217 lines, 1,210 tests. Reading that directly consumes the context
the analysis itself needs.

Fan-out resolves this without bending the rule. Every test is still read in full. The
reading is distributed across agents, and the results are merged with a completeness check.

**Use it above roughly 6,000 lines of test code. Below that, read them yourself** — the
coordination overhead exceeds the benefit, and one reader holding the whole suite spots
cross-file patterns more easily.

---

## Step 1 — Partition by line count

Balance by **lines, not file count**. One 3,000-line file outweighs six 300-line ones, and
a naive split by file count leaves one reader with most of the work.

```bash
python3 - <<'PY'
import pathlib
files = sorted((p, len(p.read_text(errors='replace').splitlines()))
               for p in pathlib.Path('.').glob('__tests__/**/*.test.*'))
files.sort(key=lambda t: -t[1])          # longest first
N = 6
groups, load = [[] for _ in range(N)], [0]*N
for p, n in files:                       # greedy bin packing
    i = load.index(min(load))
    groups[i].append(p.as_posix()); load[i] += n
for i, g in enumerate(groups):
    print(f"group {i+1}: {len(g)} files, {load[i]:,} lines")
    for p in g: print("   ", p)
PY
```

Target 5–7 groups of roughly 3,000–4,000 lines. Fewer, larger groups risk a reader running
out of context mid-file; more, smaller groups add coordination cost without improving
coverage.

Adjust the glob for the ecosystem: `test_*.py` and `*_test.py` for pytest.

---

## Step 2 — Spawn readers

Spawn all readers **in a single message** so they run concurrently rather than in sequence.

Each reader gets the same rubric verbatim and its own **disjoint** file list. Never give two
readers the same file — duplicated work inflates the merged counts and breaks the
completeness check in step 3.

### Prompt template

> You are assessing TEST QUALITY for a test-suite assessment. Repository: `<absolute path>`
>
> Read these test files IN FULL. Do not sample. Read every test in every file:
> `<file list with line counts>`
>
> For EVERY test, judge one thing: does it verify behavior, or does it merely execute code?
> Then classify weak tests into these categories. A test may fall into several.
>
> `<paste Categories 1–5 verbatim from references/test-quality-rubric.md>`
>
> Return a structured report:
>
> 1. **Per file**: path, number of tests, how many genuinely verify behavior, how many weak.
> 2. **Weak tests**: `file:line`, category, and a SHORT QUOTED excerpt of the actual code
>    proving the classification. Quoting is mandatory — a judgment without quoted evidence
>    is unusable.
> 3. **Skip/only markers**: exact locations, and the stated reason or "reason not stated".
> 4. **Mocking posture**: what each file mocks, and whether tests assert on outcomes or on
>    the mocks. Note if a file mocks its subject so heavily nothing real runs.
> 5. **Genuinely good tests**: name 2–4 of the strongest and say briefly why.
> 6. **Anything that surprised you** about what these tests do or do not verify.
>
> Be concrete and quote line numbers. Do not fix anything. Do not modify any file. This is
> read-only.

Two elements of that template are easy to drop and both matter.

**The mandatory quote** is what makes the merge tractable. It lets you spot-check any claim
in seconds and it makes the verification pass possible. Readers that return unquoted
judgments have produced opinions you cannot act on.

**The request for good tests** prevents a merged report that reads as uniformly damning. A
report listing only problems gives the reader no way to calibrate the ones it lists, and on
a decent suite it is simply inaccurate.

Ask for "mocking posture" explicitly. In practice it surfaces structural findings that
per-test classification misses — the highest-value finding in one real run was that a shared
mocking pattern made an entire class of authorization bug undetectable, which no individual
test classification would have revealed.

---

## Step 3 — Merge, and check completeness

**Cross-check the count.** Sum the readers' test-case counts and compare against the total
the test runner reported.

- Delta under ~1%: the reading was complete. Report the delta in the assessment.
- Larger delta: files were missed or double-counted. Find out which before writing anything.

This check is cheap and it is the only evidence that fan-out actually achieved what direct
reading would have. Include it in the report's method note so a reader can judge it too.

**Check the arithmetic of each reader's own table.** Rows where "verifies" plus "weak" does
not equal the case count have appeared in practice. Do not propagate them.

**Treat convergence as evidence.** When several readers independently report the same
structural problem in different files, that is much stronger than one reader's opinion —
they had no contact and no shared context beyond the rubric. Say so in the report: "reported
independently by four readers" is a meaningful claim about reliability.

**Spot-check the sharpest claims yourself** against the source before writing them down.
Readers are usually right and occasionally not. Verify anything that will land in the top
risk tier.

**State the aggregate's limits.** A merged weak-test count is the sum of several independent
judgments and is softer than any measured number. Say so in the degradations section rather
than presenting it with the confidence of a measurement. Individual classifications, each
backed by a quote, are firmer than the total.

---

## The decisive experiment

When the assessment concludes that a suite would fail to catch a specific defect, that is
**testable rather than arguable**, and testing it is worth far more than more prose.

This requires temporarily modifying production code, which Rule 1 otherwise forbids. It is
permitted only under this controlled procedure, only when the user has approved it, and
never delegated to a subagent — you must control the restore.

```bash
# 1. Back up outside the repository
cp <target> /tmp/scratch/target.backup

# 2. Make the minimal mutation (e.g. delete one authorization filter)

# 3. Run only the tests that claim to cover it
npx jest <specific test file> --ci        # or: pytest <specific test file>

# 4. Restore unconditionally and verify TWO ways
git checkout -- <target>
git status --porcelain <target>           # must be empty
diff -q /tmp/scratch/target.backup <target>   # must be identical
```

If the suite stays green, the finding is demonstrated rather than inferred, and the report
should say so in exactly those terms. In one real run, removing both authorization guards
from a server action left all 39 of its tests passing — which turned a well-argued inference
into a fact a reader cannot dismiss.

Report the restore verification in the assessment. A reader needs to know the repository was
left as it was found.

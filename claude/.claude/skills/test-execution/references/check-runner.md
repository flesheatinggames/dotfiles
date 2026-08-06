# The Check Runner

The eight kinds it runs, and the mutation protocol in full. R-5.4 to R-5.6, R-8.1 and R-8.2.

**The executor never grades its own checks.** Everything here is a script for that reason
rather than for speed. An agent deciding whether its own work passed decides generously — not
from bad faith, but because it knows what it meant, and the check is supposed to be read by
someone who does not.

## The eight kinds

Five are authored by the plan. Three are implied: nothing writes them, and they run anyway.

| Kind | Authored? | Passes when |
|---|---|---|
| `file-exists` | yes | The named file exists, or is absent when `absent: true` |
| `tests-pass` | yes | The command exits zero **and** every named test appears in its output |
| `guard-holds` | yes | The characterization tests guarding a seam still pass |
| `pattern-count` | yes | A regular expression occurs the stated number of times across the stated scope |
| `mutation` | yes | The named edit makes the named tests fail **by assertion** — see below |
| `coverage-delta` | implied, one per entry in the item's own field | The measured figure reaches the target |
| `claim-annotations` | implied, from the item's `claims` | Every claim has at least one annotated test |
| `standing-invariant` | implied, always | The suite is green except the registry and pre-flight's recordings |

### Two things that surprise people

**A `tests-pass` check that names tests, run by a quiet reporter, is reported `not-run`.** The
check is that those tests *ran*; when the output does not name them, that is unknown rather
than true, and R-10.2 forbids inferring it. A passing run of zero tests satisfies an exit code,
which is precisely what naming tests exists to prevent. The fix belongs in the plan — give the
command a reporter that prints names, `-v` for pytest — and never here, because editing a check
is forbidden.

**A `pattern-count` expecting zero across files that do not exist is reported `not-run`.** Zero
matches across zero files is not evidence of removal; it is the shape the check takes when the
scope path is wrong, and it would otherwise pass for exactly the wrong reason.

## The mutation protocol

This is the only check that modifies production code, and it is the only one that verifies
assertion strength. It is also the one where a small implementation shortcut produces
confident nonsense, so the protocol is not optional and every deviation fails the check.

### Applying the edit is model work; everything else is one process

`mutation` is prose — "delete the `.eq('user_id', user.id)` filter at line 476" — and reading
it is judgment. So:

1. **You** copy the target file to the scratch directory, **outside the repository**, and make
   the named edit there. Only that edit.
2. **The script** does everything else, in one process.

```bash
cp tally/money.py "$SCRATCH/money.mutated.py"
# apply the named edit to $SCRATCH/money.mutated.py
python3 <skill>/scripts/check_runner.py docs/test-plan.md --item WI-06 \
        --mutation-check C1 --mutated-file "$SCRATCH/money.mutated.py" --repo . --json
```

**Never delegate a mutation check to a subagent.** Whoever writes into the repository controls
the restore, in the same process, in a `finally`. A delegating side cannot see a failure that
kills the delegate, and the repository is left modified by something nobody watched.

### What the script does, in order

1. **Back up the target outside the repository**, so no repository operation — a checkout, a
   clean, a reset — can reach the only copy of the original. Record the file's git status
   *before* anything changes.
2. **Write a recovery record** to the sidecar naming the backup and its target.
3. **Run the command before mutating.** This costs a third run and buys two things: the set of
   tests already failing, and the knowledge that the named test is not one of them. A test that
   fails before the edit and after it has not been shown to detect anything.
4. **Apply the mutation, and clear the bytecode caches.** See below; this line is the one that
   was missing.
5. **Run the named command.**
6. **Read the result**: did the named tests fail, and did they fail *by assertion*?
7. **Restore.** Run the plan's named restore command, clear the caches again, and compare the
   file byte for byte against the backup. Where the named command did not by itself restore
   it, restore from the backup and **fail the check**, recording why.
8. **Verify two ways**: the file matches its backup, and its git status is what it was before.
9. **Re-run the command** and require the same tests to fail as before the mutation.
10. **Remove the recovery record.**

### Assertion, not error

R-5.6 turns on this and it is easy to miss. A test that **errors** under mutation proves it
reaches the code and proves nothing about what it asserts. Deleting a function so that every
test importing it explodes would otherwise satisfy every mutation check in a plan at once.

The runner classifies the failure and says which signal decided it. Where it cannot tell, it
reports `not-run` rather than guessing — a worse outcome for the run and an honest one.

### The bytecode cache, which is why step 4 exists

**Without clearing compiled-bytecode caches the protocol reports fiction, and every
verification R-5.6 asks for still passes.**

CPython records the source file's modification time, to a whole second, in the `.pyc` header.
A mutation applied and restored inside the same second leaves a source file whose recorded time
and size are unchanged — the case that exposed this changed one `+` to a `-`, so the size was
identical — and the interpreter reuses the stale bytecode. What was observed: a file verified
byte-identical to its backup by two independent checks, and a test run that behaved as though
the mutation were still in place.

That is the worst shape a failure here can take. So the caches go after the mutation is applied
and after every restore. It is a no-op in ecosystems that do not cache this way.

### Restoring, and why `git checkout --` is not enough

Every restore command real plans write is `git checkout -- <file>`. That is wrong whenever the
item has legitimately modified the file and not yet committed it — **a seam item is always that
case** — because it would silently destroy the item's work.

So the backup is the ground truth. The named command runs because R-5.6 requires it, and the
check **fails** when the named command did not by itself produce a byte-identical file, with a
detail saying so. The tree is safe either way and the deviation is reported rather than hidden.

The second of R-5.6's two verifications changes shape for the same reason: the file's git
status must match what it was *before* the mutation, not be empty. "Empty" is right only for a
file the item has not touched, which is not the interesting case.

### Crash safety

A protocol that only restores on the happy path is worse than none, because it teaches people
to trust it. Three layers:

- A `finally` that restores from the backup.
- Handlers for interrupt, terminate, and hangup that restore and re-raise.
- A **recovery record** on disk, for a kill that catches nothing. Every run of the check runner
  reads it at startup and restores before doing anything else.

```bash
python3 <skill>/scripts/check_runner.py docs/test-plan.md --recover --repo .
```

If the backup is gone — temporary directories do not survive a reboot — the recovery says so
loudly and tells you to restore by hand and check the diff first, because the item may have had
uncommitted work in that file.

## Suspension, and what it is not

A mutation check whose claim has a test standing red in the defect registry is recorded
`suspended`, **never passed** (R-7.4). Mutating code against an already-failing test proves
nothing about whether the suite can detect the defect. It activates when the test goes green.

`suspended` is not a softer `passed`. The run summary reports it as an obligation still
outstanding, and the linter fails a plan that records such a check as passed.

## Coverage deltas

Every entry in an item's `coverage-delta` field is an implied check (R-5.5). There is
deliberately no `coverage-delta` check kind: it was both a field and a kind for a while, and
the two copies drifted inside a single writing session.

The baseline comes from `--record-baseline`, run once immediately after slice zero, because
slice zero rewrites the coverage configuration and a figure measured before it is against a
denominator that has stopped existing.

A file the coverage report does not mention is reported `not-run`, not zero. **A file nobody
measured and a file measured at zero are different facts**, and the second is the only one that
says anything about the tests.

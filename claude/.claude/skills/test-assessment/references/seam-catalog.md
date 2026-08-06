# Seam Catalog

A **testability seam** is a small, mechanical change to production code that makes a
piece of behavior reachable by a unit test.

**This catalog is closed.** Exactly four seam types are permitted. Recommendations
outside it — new architectures, interface hierarchies, dependency injection frameworks,
adopting a new library, general redesign, "consider a hexagonal architecture" — are
prohibited.

**Closed means four types, not four literal examples.** Each seam below states a
*principle* and then gives examples of it. Seam 3 in particular covers environment
boundaries generally, not only the clock, filesystem, and network. Apply the principle;
do not argue by analogy from an example. If you find yourself constructing an argument
that X is "like" the filesystem in order to justify a recommendation, stop — either X
meets the stated principle directly, in which case say so plainly, or the recommendation
does not belong in the report.

Use `scripts/census.py` to find the call sites for these categories. It counts
deterministically, with comments and string literals stripped. **Do not count them by
hand** — every report that has done so has miscounted.

If no catalog seam fits a piece of code, say so plainly and classify the code as reachable
only by integration-style tests. That is a legitimate and useful finding. Inventing a
fifth seam type is not.

Every recommendation must name its seam type, give the exact file and line, state the
behavior that becomes testable, give a size estimate, and be **paired with a
characterization test**. A recommendation missing any of these is incomplete.

---

## Seam 1 — Extract a pure function

**When.** A method mixes decision logic with input and output. The logic is worth testing;
the surrounding reads and writes are what make it unreachable.

**The change.** Move the decision logic into a function that takes plain values and
returns a plain value. The original method keeps doing the input and output, and calls the
new function.

**Recognize it by.** A function that reads something, computes something, and writes
something, where the middle part contains the branches. Long functions whose complexity
score is high but whose inputs are mostly derived from a single fetch.

**Size.** Usually small. Larger when the logic is threaded through the reads and writes
rather than sitting in a block.

**What becomes testable.** The decision logic, directly, with ordinary values and no test
doubles at all. This is the highest-value seam and should be preferred when more than one
seam would work.

### The minimal form: export only

Sometimes the extraction has already happened. The function is already pure, already sits
on its own, and takes plain values and returns a plain value — and the only thing keeping
a test from reaching it is that the module does not expose it. The seam then degenerates
to **adding an `export` and nothing else**.

**Recognize it by.** A module-private function (no `export` in TypeScript or JavaScript, a
leading underscore by convention in Python) whose body reads only its parameters. If you
find yourself describing the extraction as "move the function to the top level" and it is
already at the top level, this is what you have.

**The change.** Add the keyword. No logic moves. No call site changes. Nothing is
reordered.

**Size.** Trivial, and say "trivial" rather than "small" so the planner can size the item
honestly — this is a one-token edit, not an afternoon.

**The characterization test is not required for this form**, and this is the one place in
the catalog where the pairing is waived. The pairing exists because restructuring untested
code can change its behavior. Adding an export restructures nothing, so there is no
behavior change for a characterization test to catch, and writing one would be scaffolding
against a risk that does not exist. Say explicitly in the recommendation that the minimal
form applies and that this is why no characterization test accompanies it — an unexplained
missing pairing reads as an omission.

**Prefer this form wherever it suffices.** Where a function needs no logic moved,
recommending the full extraction asks for work that cannot make the code more testable
than the export already does, and carries the behavior-change risk the full form always
carries.

**Where it does not suffice.** If the function reads anything outside its parameters —
module-level state, an imported singleton, the environment — exporting it makes it
reachable but not deterministic, so the test you could then write would still not be a
unit test. That is a different seam (usually seam 2 or seam 3), not this one, and the
recommendation must say which.

---

## Seam 2 — Pass the dependency in as a parameter

**When.** A function constructs its own collaborator inside itself — a client, a
connection, a service object — so a test cannot substitute one.

**The change.** Accept the collaborator as a parameter. Where callers should not have to
supply it, give the parameter a default that constructs the current object, so existing
call sites keep working unchanged.

**Recognize it by.** A `new Something()` or `Something()` call inside a function body,
where `Something` reaches outside the process. Module-level singletons referenced directly
from inside functions.

**Size.** Small when the construction happens in one place. Medium when the same
collaborator is constructed in several functions and the change should be consistent.

**What becomes testable.** Everything the function does with that collaborator, using a
stub, without the real database, network, or service.

**Caution.** Do not let this become a dependency injection framework. One parameter with a
default value. Nothing more.

---

## Seam 3 — Wrap a direct call to an environment boundary

**The principle, which is what makes this seam apply: the code reads or writes state that
lives outside the function and outside its arguments, so its behavior depends on the
environment rather than only on its inputs.** Anything meeting that description is in
scope. The clock, the filesystem, and the network are the canonical examples, not the
whole list.

Other things that meet it, and have come up in real assessments: browser persistent
storage (`localStorage`, `sessionStorage`), media queries (`window.matchMedia`), the
random number generator, environment variables, the current working directory, the system
locale and timezone, and process-level globals.

**This is a widening of the principle, not a licence to leave the catalog.** The test is
specific: does the function reach outside itself for state, and would supplying that state
make the behavior deterministic? Convenience, aesthetics, or "this would be cleaner" are
not the test. If a piece of code fails this test and none of the other three seams fits,
classify it as reachable only by integration-style tests and say so.

**When.** Code calls `datetime.now()`, `Date.now()`, `time.time()`, `open()`,
`fs.readFile`, `fetch`, `requests.get`, `localStorage.getItem`, `window.matchMedia`,
`process.env`, or `random` directly.

**The change.** Put the call behind a small substitutable thing — a function parameter, a
tiny interface with one or two methods, or an injected object. A test then supplies a
fixed clock, an in-memory file, or a canned response.

**Recognize it by.** Grep for the calls. Time-dependent code is the most common instance
and the most common source of tests that pass in the morning and fail at midnight, or fail
in another timezone.

**Size.** Small for a clock. Medium for the filesystem or network, because there are
usually several call sites and the wrapper's shape has to cover all of them.

**What becomes testable.** Behavior that varies with time, file contents, or remote
responses — including the error paths, which are otherwise nearly impossible to reach.

**Caution.** Wrap the boundary, not the domain. The wrapper should be thin enough that
nobody would want to test the wrapper itself.

---

## Seam 4 — Move real work out of a constructor

**When.** Creating an object opens a connection, reads a file, starts a thread, makes a
network call, or performs expensive setup, so a test cannot create the object cheaply —
or at all — without the real environment.

**The change.** Move the work into an explicit initialization method the caller invokes,
or make it lazy so it happens on first use. The constructor only assigns fields.

**Recognize it by.** Constructors and `__init__` methods containing anything beyond
assignment. React components performing side effects during render rather than in an
effect.

**Size.** Medium. Every construction site may need to call the new initializer, and
getting laziness right takes care.

**What becomes testable.** Every method on the object, because the object can now be
created in a test without its environment.

**Caution.** This is the largest of the four seams and the one most likely to change
behavior accidentally. Its characterization test matters most.

---

## Characterization tests: the required pairing

A characterization test is a coarse test that pins down the code's **current observable
behavior** at whatever boundary is already testable. It is written *before* the seam
refactoring so the refactoring can be verified as behavior-preserving.

Refactoring untested code is exactly the situation where refactoring is most dangerous.
The pairing is what makes a seam recommendation safe for a later stage to execute.

Characterization tests are **scaffolding, not part of the final suite**. They capture what
the code does, correct or not. Once the seam exists and real unit tests cover the behavior,
they are removed. Say this in the report so nobody mistakes them for the goal.

For each one, describe concretely:

1. **The boundary** it captures behavior at — the outermost point already reachable
   without changing anything. Often a whole module's public function, a command-line
   entry point, or a rendered component.
2. **The inputs** — specific values, chosen to exercise the branches the seam will expose.
   Include at least one error or edge case, since those paths break most often under
   refactoring.
3. **What is observed** — the return value, the written output, the calls made to the
   outside world, the rendered result. Whatever is visible without modifying the code.
4. **Known imprecision** — if the behavior depends on the current time, randomness, or
   ordering, say how the test pins that down, or say that it cannot be fully pinned and
   what remains uncontrolled.

If a characterization test genuinely cannot be written before a given seam — the code has
no reachable boundary at all — then the seam recommendation is **not safe** and the report
must say so rather than recommending it anyway. That situation is itself a top-tier
finding.

---

## Choosing between seams

When more than one seam would work, prefer them in this order:

0. **Export only** — the minimal form of seam 1. Nothing moves, so nothing can break
1. **Extract a pure function** — no test doubles needed afterward, smallest risk
2. **Pass the dependency in** — one parameter, mechanical, easy to verify
3. **Wrap the clock, filesystem, or network** — more call sites, more design judgment
4. **Move work out of a constructor** — largest, most likely to change behavior

**Check the minimal form first, every time.** Before recommending a full extraction, ask
whether the function you want to extract is already extracted and merely unexported. Where
it is, the export-only form is preferred and the full extraction is over-recommendation: it
asks for behavior-changing work that buys nothing the keyword does not already buy. The
minimal form still counts as seam type 1 in the index, so the classification stays inside
the closed catalog; what changes is the size, and whether a characterization test is
required.

State why you chose the one you chose when the choice was not obvious.

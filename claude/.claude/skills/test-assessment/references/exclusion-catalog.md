# Exclusion Catalog

Code that does not warrant unit testing. Excluding it produces **effective coverage** —
coverage of the code that actually matters — which is reported alongside the raw number.

Two rules govern every exclusion:

1. **State the reason.** An exclusion without a reason is indistinguishable from hiding a
   problem. Every excluded path or file gets a category and a sentence.
2. **When in doubt, do not exclude.** An over-inclusive assessment is honest and merely
   pessimistic. An over-exclusive one inflates effective coverage and misleads the reader,
   which is the failure mode this whole report exists to prevent.

Note which exclusions belong in the coverage tool's own configuration — `omit` under
`[tool.coverage.run]` for Python, `coverage.exclude` for Vitest, `coveragePathIgnorePatterns`
for Jest — so a later stage can apply them and get the same number.

---

## Category A — Generated code

Code produced by a tool from another source. Testing it tests the generator.

Protocol buffer and gRPC stubs; GraphQL client types; OpenAPI clients; ORM model
scaffolding; parser output; `*.pb.go`, `*_pb2.py`, `*.generated.*`, `*.g.dart`; anything
under a `generated/` or `__generated__/` directory; files whose header says they are
generated and should not be edited.

**Verify before excluding.** Some "generated" files get hand-edited over time. Check the
version control history for manual changes. If it has been edited by hand, it is source
code now, and it needs testing.

---

## Category B — Vendored and third-party code

Dependencies copied into the tree. Not the project's code and not its responsibility.

`node_modules/`, `vendor/`, `third_party/`, `.venv/`, `venv/`, `site-packages/`, bundled
libraries.

This is usually excluded by tooling defaults already. Check that it actually is —
coverage reports that include `node_modules` produce absurd denominators, and an
absurd denominator is worth reporting as a configuration finding on its own.

---

## Category C — Framework boilerplate

Code whose only content is a framework's required shape, carrying no decision of the
project's own.

Application entry points that only wire things together; route or URL declaration files
containing no logic; Django `apps.py` and `wsgi.py`; framework configuration modules;
React `main.tsx` that only mounts the root; barrel files (`index.ts` that only re-exports);
`__init__.py` files that only re-export.

**The boundary is decision content.** The moment a route file starts choosing handlers
conditionally, or an entry point reads configuration and branches on it, it stops being
boilerplate and needs testing. Read it before excluding it.

---

## Category D — Database migrations

Migration files are run once against real data. A unit test of a migration verifies
almost nothing worth knowing, and migrations should be validated by running them against
a realistic database instead.

Alembic `versions/`, Django `migrations/`, Rails `db/migrate/`, Prisma `migrations/`,
raw SQL migration directories.

**The exception.** A migration containing substantial data-transformation logic in
application code — not SQL — is real logic and should be tested, usually by extracting
the transformation into a pure function (Seam 1) and testing that. Note this when you see
it, as it is a genuine finding rather than an exclusion.

---

## Category E — Trivial accessors and pure data

Code with no behavior to verify. A test would restate the field name.

Getters and setters that only read or assign a field; dataclasses, Pydantic models, and
TypeScript interfaces or types with no logic; constant and enum definitions; simple
`__repr__` and `toString` implementations; pass-through wrappers that only forward
arguments unchanged.

**Not trivial**, despite appearances: property getters that compute something; Pydantic
validators and custom serializers; dataclasses with `__post_init__` logic; any accessor
with a branch in it. Read the body — the shape of the declaration does not settle it.

---

## Category F — Dead code

Code nothing reaches. Testing it is worse than not testing it, because a passing test
implies the code matters.

Unreferenced functions and modules; code behind permanently false conditions; commented-out
blocks; unreachable branches after an unconditional return or raise; old implementations
kept beside their replacements.

**Verify reachability before calling it dead**, and say how you verified. Static search
misses dynamic dispatch, reflection, string-keyed lookup, plugin registration, framework
autoloading, and public interfaces used by consumers outside the repository. When you
cannot establish that nothing reaches it, mark it *possibly dead* and recommend
confirming it — do not exclude it.

Dead code is a finding in its own right, not only an exclusion. Recommend deleting it,
which is the one code change this stage may recommend without a seam.

---

## Explicitly not excludable

These get tested. They are where bugs live.

- **Error handling and exception paths.** Under-tested precisely because they are
  awkward to reach; that is an argument for a seam, not an exclusion.
- **Logging that carries logic.** A log line inside a branch is evidence of a decision.
- **Configuration parsing and validation.** Real logic with real failure modes.
- **Serialization and deserialization.** A common source of silent data corruption.
- **Anything hard to test.** Difficulty is a testability finding and a seam
  recommendation. It is never a reason to exclude. Excluding code because it is hard to
  test is the exact failure this report exists to expose.

---

## Reporting exclusions

Produce a table: path or pattern, category, reason, and lines excluded. Then report both
numbers together, always in this shape:

> Raw coverage 34% of 4,210 statements. Effective coverage 41% of 3,480 statements after
> excluding 730 statements across 22 files.

Never report effective coverage alone. The gap between the two numbers is information,
and a reader who sees only the flattering number cannot judge the exclusions.

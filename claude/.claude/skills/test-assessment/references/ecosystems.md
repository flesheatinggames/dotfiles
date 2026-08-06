# Ecosystem Detection and Measurement

## Enforcing the time budget portably

**`timeout` does not exist on macOS.** It is part of GNU coreutils, where it is installed
as `gtimeout` if present at all. A command written as `timeout 600 npm test` fails with
`command not found` on a stock Mac and the budget silently does not apply.

Enforce the budget in Python instead, which works everywhere:

```bash
python3 - <<'PY'
import subprocess, time
cmd = ["npx", "jest", "--coverage", "--coverageDirectory=/tmp/cov", "--ci"]
start = time.time()
try:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    print((p.stdout or "") + (p.stderr or ""))
    print(f"exit={p.returncode} elapsed={time.time()-start:.0f}s")
except subprocess.TimeoutExpired:
    print("SUITE EXCEEDED BUDGET AND WAS STOPPED")
PY
```

Report a suite stopped at the budget as a degradation, and continue with whatever partial
data exists.



Supported with full measurement in this version: **Python with pytest**, and
**TypeScript or JavaScript with Vitest or Jest**.

Everything else still gets a report — the behavioral map, exclusions, testability
classification, and seam recommendations are language-independent. Only coverage numbers
and cyclomatic complexity degrade, and the Degradations section must say so.

---

## Distinguishing unit tests from end-to-end tests

Do this before anything else. It is the most common way an assessment goes wrong.

Playwright and Cypress run a real browser against a running application. They are not
unit tests. A repository with a large Playwright suite and no unit tests looks tested
from the outside and is not.

Signals that a test directory is end-to-end rather than unit:

- `@playwright/test` or `cypress` in the manifest
- A `playwright.config.*` or `cypress.config.*` file
- Imports of `@playwright/test`, `cypress`, `puppeteer`, or `selenium`
- Directories named `e2e`, `integration`, `acceptance`, `browser`, or `tests/playwright`
- Tests that navigate to a URL, start a server, or drive a browser

Count end-to-end tests separately in the inventory. Report them as their own line. Never
let them stand in for unit coverage. They may be valuable — say so if they are — but they
answer a different question and they do not make a unit suite trustworthy.

The same applies to Python: tests using `httpx.AsyncClient` against a live server,
`testcontainers`, or a real database connection are integration tests, not unit tests.

---

## Python with pytest

### Detection

| Signal | Meaning |
|---|---|
| `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`, `Pipfile` | Python project |
| `[tool.pytest.ini_options]` in `pyproject.toml`, or `pytest.ini`, `tox.ini`, `conftest.py` | pytest configured |
| `pytest-cov` in dependencies, or `[tool.coverage.*]`, `.coveragerc` | coverage configured |
| `test_*.py` or `*_test.py` files, `tests/` directory | test files |
| `pytest-asyncio`, `anyio` | async tests; needed to run them at all |

Check for a virtual environment before running anything: `.venv/`, `venv/`, `env/`, or an
active `VIRTUAL_ENV`. Prefer `.venv/bin/python` if it exists. If dependencies are not
installed, the suite will fail to collect and that is a broken suite, not a failing one —
diagnose and report it as such.

**Never install dependencies.** That modifies the environment. Report what is missing.

### Running the suite with coverage

Pass configuration on the command line so nothing is written into the repository:

```bash
python3 -m pytest --cov=<source-package> \
                  --cov-report=json:<tmp>/coverage.json \
                  --cov-report=term-missing \
                  --cov-branch \
                  -q
```

Write coverage output to a temporary directory outside the repository. `--cov-branch`
gives branch coverage, which pytest-cov supports.

If `pytest-cov` is not installed, try `coverage run -m pytest` then
`coverage json -o <tmp>/coverage.json`. If neither is available, report that coverage
tooling is unavailable and continue with static analysis only.

Record the versions: `python3 -m pytest --version` and `python3 -m coverage --version`.

### Collect-only first

Run `python3 -m pytest --collect-only -q` before the real run. It is fast and it
separates "the suite is broken" (collection errors) from "tests fail" (assertions fail).
The report treats these differently.

### Skip markers to find

`@pytest.mark.skip`, `@pytest.mark.skipif`, `@pytest.mark.xfail`, `pytest.skip()` called
inside a test body, and `pytestmark = pytest.mark.skip` at module level, which disables an
entire file and is easy to miss.

---

## TypeScript and JavaScript

### Detection

| Signal | Meaning |
|---|---|
| `vitest` in devDependencies, `vitest.config.*`, or a `test` block in `vite.config.*` | Vitest |
| `jest` in devDependencies, `jest.config.*`, or a `jest` key in `package.json` | Jest |
| `@vitest/coverage-v8` or `@vitest/coverage-istanbul` | Vitest coverage available |
| `collectCoverage` or `coverageDirectory` in Jest config | Jest coverage configured |
| `*.test.ts`, `*.test.tsx`, `*.spec.ts`, `*.spec.tsx`, `__tests__/` | test files |
| `@testing-library/react` | component tests |
| `@playwright/test`, `cypress` | end-to-end, not unit — see above |

Read the `scripts.test` field in `package.json`. If it is absent, or is
`echo "Error: no test specified" && exit 1`, there is no test suite. That is a finding,
not an error.

Detect the package manager from the lockfile: `pnpm-lock.yaml`, `yarn.lock`,
`package-lock.json`, or `bun.lockb`. Use the matching runner.

**Monorepos.** If `workspaces` appears in `package.json`, or a `pnpm-workspace.yaml`
exists, each workspace package has its own suite and its own coverage. Assess each, and
produce one report with a section per package. Do not average coverage across packages —
that number means nothing.

### Running with coverage

Vitest, passing config on the command line:

```bash
npx vitest run --coverage \
               --coverage.provider=v8 \
               --coverage.reporter=json \
               --coverage.reporter=lcov \
               --coverage.reportsDirectory=<tmp>/coverage
```

Jest:

```bash
npx jest --coverage \
         --coverageReporters=json-summary \
         --coverageReporters=lcov \
         --coverageDirectory=<tmp>/coverage \
         --ci
```

Both write LCOV, which `scripts/parse_coverage.py` reads. Point the output directory
outside the repository.

If the coverage provider is not installed, Vitest will offer to install it. **Decline.**
Installing modifies the repository. Report that coverage tooling is not configured.

Record versions with `npx vitest --version` or `npx jest --version`.

### Recommending a framework where none exists

This is the common case in the target repositories. When a project has no test suite,
recommend **Vitest**, because:

- It reuses the existing Vite configuration, so there is no second build pipeline
- Coverage is built in through the v8 provider
- Its API is Jest-compatible, so knowledge and examples transfer
- It is already in use elsewhere in this codebase family

Recommend Jest only when the project already uses it, or when it is a Next.js project
whose tooling is already committed to Jest. Say which you recommend and why, in one
sentence. This is a recommendation only — stage one writes no configuration.

### Skip markers to find

`it.skip`, `test.skip`, `describe.skip`, `it.only` and `describe.only` (which silently
disable every other test in the file — a serious and easily missed finding), `it.todo`,
`test.failing`, and `xit` or `xdescribe`.

`.only` deserves special attention. A committed `.only` means the suite has been running
a fraction of its tests, possibly for a long time, while appearing green.

### React component specifics

A component test that renders and asserts nothing but "it did not throw" is an
assertion-free test under the quality rubric. Snapshot tests (`toMatchSnapshot`) are
suspect unless there is evidence somebody reviewed the snapshot — check whether the
snapshot file was committed in the same change as a deliberate behavior decision, or just
generated.

Testing hooks, reducers, and pure helper functions is usually straightforward. Components
that fetch data directly, read from context they construct themselves, or touch
`window`/`localStorage`/`Date` in render need seams. That distinction drives the
testability classification for React code.

---

## Coverage output formats the parser handles

| Format | Produced by | Detection |
|---|---|---|
| `coverage.py` JSON | `pytest --cov-report=json`, `coverage json` | `.json` with a `files` key and `meta.version` |
| Cobertura XML | `coverage xml`, many CI tools | `.xml` with a `<coverage>` root |
| LCOV | Vitest, Jest, c8, nyc, Istanbul | `lcov.info`, lines starting `SF:` |
| Istanbul JSON | Vitest and Jest `json` reporter | `.json` keyed by absolute file path with `statementMap` |
| Go coverage profile | `go test -coverprofile` | first line is `mode: set|count|atomic` |

The Go profile is handled even though Go is not otherwise supported in this version,
because the format is trivial and costs nothing.

**LCOV and Istanbul JSON do not agree on the denominator, and both are right.** LCOV
records *lines*; Istanbul records *statements*, and several statements can sit on one
line. Parsing both outputs of the same Jest run gives identical branch counts but
different line totals — for example 4,458 of 4,695 against 4,885 of 5,170, which is
94.95% against 94.49%.

This matters for the report. Name which artifact the number came from in the provenance
section, and use the same one consistently. Never present figures from the two formats
side by side as though they were comparable, and if a later stage re-measures, it must
read the same format to make a before-and-after comparison meaningful.

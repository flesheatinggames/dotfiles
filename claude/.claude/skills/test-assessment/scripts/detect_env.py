#!/usr/bin/env python3
"""Detect languages, test frameworks, test commands, and coverage configuration.

Reads manifests and configuration files. Runs nothing and installs nothing.

Every finding is tagged with how it was determined: "read" when taken directly from a
file, "inferred" when deduced. Requirement R-5.1 says guesses must be recorded as
guesses, so the caller must carry the tag into the report.

Usage:
    python3 detect_env.py --repo . --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Directories never worth walking into.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt", ".svelte-kit",
    "target", "vendor", "third_party", "coverage", ".coverage", "htmlcov", ".tox",
    ".idea", ".vscode", "site-packages", ".turbo", ".cache", "out",
}

# A test file living in one of these, or matching one of the e2e signals below, is an
# end-to-end test rather than a unit test. Keeping them apart matters: a large Playwright
# suite makes a repository look tested when it has no unit tests at all.
E2E_DIR_NAMES = {"e2e", "integration", "acceptance", "browser", "playwright", "cypress"}
E2E_IMPORT_RE = re.compile(
    r"""from\s+['"](@playwright/test|cypress|puppeteer|selenium[\w-]*)['"]"""
    r"""|require\(['"](@playwright/test|cypress|puppeteer)['"]\)"""
    r"""|^\s*import\s+(playwright|selenium)\b""",
    re.MULTILINE,
)
PY_INTEGRATION_RE = re.compile(
    r"\b(testcontainers|httpx\.AsyncClient|TestClient\(|psycopg2?\.connect|"
    r"create_engine\(|docker\.from_env)\b"
)

JS_TEST_FILE_RE = re.compile(r".*\.(test|spec)\.(ts|tsx|js|jsx|mts|cts)$")
PY_TEST_FILE_RE = re.compile(r"^(test_.*\.py|.*_test\.py)$")

# Skip markers. `.only` is listed separately by the caller because a committed `.only`
# silently disables every other test in its file while the suite still reports green.
JS_SKIP_RE = re.compile(
    r"\b(?:it|test|describe)\.(skip|todo|failing)\b|\b(xit|xdescribe)\s*\("
)
JS_ONLY_RE = re.compile(r"\b(?:it|test|describe)\.only\b")
PY_SKIP_RE = re.compile(
    r"@pytest\.mark\.(skip|skipif|xfail)\b|\bpytest\.skip\s*\(|"
    r"^\s*pytestmark\s*=\s*pytest\.mark\.(skip|skipif|xfail)",
    re.MULTILINE,
)


def walk(root: Path):
    """Yield every file under root, skipping vendored and build directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_json(path: Path) -> dict:
    try:
        return json.loads(read(path))
    except (ValueError, OSError):
        return {}


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- node


def detect_node(root: Path, manifests: list[Path]) -> list[dict]:
    """One entry per package.json, so monorepo workspaces stay separate.

    Coverage must never be averaged across workspace packages; the combined number is
    meaningless. Each package is assessed on its own.
    """
    out = []
    for mf in manifests:
        pkg = load_json(mf)
        if not pkg:
            continue
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        scripts = pkg.get("scripts", {}) or {}
        pkg_dir = mf.parent

        frameworks = []
        if "vitest" in deps:
            frameworks.append("vitest")
        if "jest" in deps or "ts-jest" in deps or "jest" in pkg:
            frameworks.append("jest")
        if "mocha" in deps:
            frameworks.append("mocha")

        e2e = [n for n in ("@playwright/test", "cypress", "puppeteer") if n in deps]

        # Config files sitting beside this manifest.
        configs = [f.name for f in pkg_dir.iterdir()
                   if f.is_file() and re.match(
                       r"^(vitest|jest|playwright|cypress|vite)\.config\.[mc]?[jt]s$", f.name)]

        # Vitest is often configured inside vite.config.ts rather than its own file.
        vite_cfg = next((pkg_dir / c for c in configs if c.startswith("vite.config")), None)
        if vite_cfg and "vitest" not in frameworks and re.search(r"\btest\s*:", read(vite_cfg)):
            frameworks.append("vitest")

        cov_providers = [n for n in ("@vitest/coverage-v8", "@vitest/coverage-istanbul",
                                     "c8", "nyc") if n in deps]
        jest_cfg = pkg.get("jest", {})

        # Coverage settings usually live in a config file rather than in package.json.
        # Jest needs no separate provider -- Istanbul is built in -- so a jest config
        # mentioning coverage means coverage is available even with no coverage package
        # in the dependency list.
        cov_config_evidence = []
        for cfg_name in configs:
            text = read(pkg_dir / cfg_name)
            for key in ("coverageThreshold", "collectCoverage", "coverageDirectory",
                        "coverageReporters", "collectCoverageFrom", "coverage:"):
                if key in text:
                    cov_config_evidence.append(f"{cfg_name}: {key}")
                    break

        cov_configured = bool(cov_providers) or bool(cov_config_evidence) or bool(
            jest_cfg.get("collectCoverage") or jest_cfg.get("coverageDirectory"))

        # Jest ships Istanbul; Vitest needs @vitest/coverage-* installed separately.
        # This distinction decides whether coverage can be measured without installing
        # anything, which the assessment is forbidden from doing.
        if "jest" in frameworks:
            cov_runnable, cov_note = True, "Jest has Istanbul built in; no install needed"
        elif "vitest" in frameworks and cov_providers:
            cov_runnable, cov_note = True, f"provider present: {', '.join(cov_providers)}"
        elif "vitest" in frameworks:
            cov_runnable, cov_note = False, (
                "Vitest is present but no @vitest/coverage-* provider is installed. "
                "Coverage cannot be measured without installing one, which is forbidden. "
                "Report this as a degradation.")
        else:
            cov_runnable, cov_note = False, "no known test framework"

        test_script = scripts.get("test", "")
        no_suite = (not test_script) or "no test specified" in test_script

        out.append({
            "manifest": rel(mf, root),
            "dir": rel(pkg_dir, root),
            "name": pkg.get("name"),
            "frameworks": frameworks,
            "e2e_tooling": e2e,
            "test_script": test_script or None,
            "test_command": (f"npm test --prefix {rel(pkg_dir, root)}"
                             if test_script and not no_suite else None),
            "test_command_basis": "read" if test_script and not no_suite else "absent",
            "has_test_suite": not no_suite,
            "coverage_providers": cov_providers,
            "coverage_configured": cov_configured,
            "coverage_config_evidence": cov_config_evidence,
            "coverage_runnable": cov_runnable,
            "coverage_note": cov_note,
            "config_files": configs,
            "typescript": "typescript" in deps or (pkg_dir / "tsconfig.json").exists(),
            "react": "react" in deps,
            "workspaces": pkg.get("workspaces") or None,
            "notes": ([] if not no_suite else
                      ["No usable `test` script; treat as having no unit test suite."]),
        })
    return out


def detect_git(root: Path) -> dict:
    """Report whether the repository is under version control.

    Asks git rather than looking for a `.git` directory. A project nested inside a
    larger repository -- a workspace package, or an app inside a monorepo -- has no
    `.git` of its own but is fully tracked, and treating it as unversioned would drop
    change frequency from the risk ranking for no reason.
    """
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"present": False, "reason": f"git unavailable: {exc}"}
    if p.returncode != 0:
        return {"present": False, "reason": (p.stderr.strip() or "not a git repository")}
    top = p.stdout.strip()
    return {
        "present": True,
        "toplevel": top,
        "is_repo_root": Path(top).resolve() == root,
        "note": (None if Path(top).resolve() == root else
                 f"This directory is nested inside the repository at {top}. History "
                 "covers the whole repository, so churn figures may include sibling "
                 "projects unless the analysis is scoped to this subdirectory."),
    }


def detect_package_manager(root: Path) -> dict:
    for lock, mgr in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                      ("bun.lockb", "bun"), ("package-lock.json", "npm")):
        if (root / lock).exists():
            return {"manager": mgr, "basis": "read", "evidence": lock}
    return {"manager": None, "basis": "absent", "evidence": None}


# ------------------------------------------------------------------------- python


def detect_python(root: Path, manifests: list[Path]) -> list[dict]:
    out = []
    for mf in manifests:
        text = read(mf)
        pkg_dir = mf.parent
        low = text.lower()

        pytest_configured = (
            "[tool.pytest.ini_options]" in text
            or mf.name in ("pytest.ini",)
            or (pkg_dir / "pytest.ini").exists()
            or (pkg_dir / "conftest.py").exists()
        )
        has_pytest = "pytest" in low or pytest_configured
        cov = ("pytest-cov" in low or "[tool.coverage" in text
               or (pkg_dir / ".coveragerc").exists())

        venv = next((rel(pkg_dir / v, root) for v in (".venv", "venv", "env")
                     if (pkg_dir / v / "bin" / "python").exists()), None)
        interpreter = f"{venv}/bin/python" if venv else "python3"

        out.append({
            "manifest": rel(mf, root),
            "dir": rel(pkg_dir, root),
            "frameworks": ["pytest"] if has_pytest else [],
            "pytest_configured": pytest_configured,
            "coverage_configured": cov,
            "async_plugin": ("pytest-asyncio" if "pytest-asyncio" in low
                             else "anyio" if "anyio" in low else None),
            "virtualenv": venv,
            "interpreter": interpreter,
            "test_command": f"{interpreter} -m pytest" if has_pytest else None,
            "test_command_basis": "read" if pytest_configured else (
                "inferred" if has_pytest else "absent"),
            "collect_only_command": (f"{interpreter} -m pytest --collect-only -q"
                                     if has_pytest else None),
            "notes": ([] if venv else
                      ["No virtual environment found beside the manifest; if dependencies "
                       "are not installed the suite will fail to collect. That is a broken "
                       "suite, not a failing one. Never install anything."]),
        })
    return out


# -------------------------------------------------------------------------- tests


def classify_tests(root: Path) -> dict:
    """Split test files into unit, integration, and end-to-end, and find skip markers."""
    unit, integration, e2e = [], [], []
    skipped, only_markers = [], []

    for path in walk(root):
        name = path.name
        is_js = bool(JS_TEST_FILE_RE.match(name))
        is_py = bool(PY_TEST_FILE_RE.match(name))
        if not (is_js or is_py):
            continue

        r = rel(path, root)
        parts = {p.lower() for p in Path(r).parts[:-1]}
        text = read(path)

        looks_e2e = bool(parts & E2E_DIR_NAMES) or bool(E2E_IMPORT_RE.search(text))
        entry = {"path": r, "lines": text.count("\n") + 1}

        if looks_e2e:
            entry["reason"] = ("directory name" if parts & E2E_DIR_NAMES
                               else "imports a browser automation library")
            e2e.append(entry)
        elif is_py and PY_INTEGRATION_RE.search(text):
            entry["reason"] = "touches a live service, database, or container"
            integration.append(entry)
        else:
            unit.append(entry)

        for m in (JS_SKIP_RE if is_js else PY_SKIP_RE).finditer(text):
            skipped.append({
                "path": r,
                "line": text[:m.start()].count("\n") + 1,
                "marker": m.group(0).strip(),
            })
        if is_js:
            for m in JS_ONLY_RE.finditer(text):
                only_markers.append({
                    "path": r,
                    "line": text[:m.start()].count("\n") + 1,
                    "marker": m.group(0).strip(),
                    "severity": "top-tier",
                    "why": ("A committed `.only` silently disables every other test in "
                            "this file while the suite still reports green."),
                })

    return {
        "unit": unit,
        "integration": integration,
        "e2e": e2e,
        "counts": {"unit": len(unit), "integration": len(integration), "e2e": len(e2e)},
        "skipped": skipped,
        "only_markers": only_markers,
    }


# ------------------------------------------------------------------- requirements


REQ_DIR_NAMES = {"docs", "doc", "spec", "specs", "requirements", "adr", "adrs", "rfc",
                 "rfcs", "design", "architecture"}
REQ_NAME_RE = re.compile(
    r"(requirement|spec|design|architect|prd|adr|rfc|readme|claude|agents)", re.I)

# Agent tooling directories hold instructions written for a coding assistant, not
# statements of what the product is supposed to do. Including them floods the candidate
# list and pushes the real specification documents out of view.
TOOLING_PREFIXES = (".claude/commands", ".claude/agents", ".claude/skills",
                    ".claude/hooks", ".github/prompts", ".cursor")


def find_requirements(root: Path) -> list[dict]:
    found = []
    for path in walk(root):
        if path.suffix.lower() not in (".md", ".rst", ".txt", ".adoc"):
            continue
        r = rel(path, root)
        if r.startswith(TOOLING_PREFIXES):
            continue
        parts = {p.lower() for p in Path(r).parts[:-1]}
        in_req_dir = bool(parts & REQ_DIR_NAMES)
        name_hit = bool(REQ_NAME_RE.search(path.stem))
        if in_req_dir or name_hit:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            found.append({
                "path": r,
                "bytes": size,
                "why": "in a documentation directory" if in_req_dir else "filename suggests it",
            })
    found.sort(key=lambda d: -d["bytes"])
    return found


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="repository root")
    ap.add_argument("--json", action="store_true", help="emit JSON (default)")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    node_manifests, py_manifests, other = [], [], {"go": [], "rust": []}
    for path in walk(root):
        if path.name == "package.json":
            node_manifests.append(path)
        elif path.name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
                           "Pipfile", "pytest.ini", "tox.ini"):
            py_manifests.append(path)
        elif path.name == "go.mod":
            other["go"].append(rel(path, root))
        elif path.name == "Cargo.toml":
            other["rust"].append(rel(path, root))

    # Collapse Python manifests to one per directory, preferring the richest.
    by_dir: dict[Path, Path] = {}
    priority = {"pyproject.toml": 0, "setup.cfg": 1, "setup.py": 2, "pytest.ini": 3,
                "tox.ini": 4, "requirements.txt": 5, "Pipfile": 6}
    for mf in py_manifests:
        cur = by_dir.get(mf.parent)
        if cur is None or priority.get(mf.name, 9) < priority.get(cur.name, 9):
            by_dir[mf.parent] = mf

    node = detect_node(root, sorted(node_manifests))
    python = detect_python(root, sorted(by_dir.values()))
    tests = classify_tests(root)

    languages = []
    if node:
        languages.append("typescript" if any(p["typescript"] for p in node) else "javascript")
    if python:
        languages.append("python")
    for lang, hits in other.items():
        if hits:
            languages.append(lang)

    unsupported = [l for l in languages if l not in
                   ("python", "typescript", "javascript")]

    result = {
        "repo": str(root),
        "languages": languages,
        "supported_for_measurement": [l for l in languages if l not in unsupported],
        "unsupported_languages": unsupported,
        "package_manager": detect_package_manager(root),
        "node_packages": node,
        "python_packages": python,
        "other_manifests": other,
        "tests": tests,
        "requirements_candidates": find_requirements(root),
        "git": detect_git(root),
        "degradations": [],
    }

    d = result["degradations"]
    if not result["git"]["present"]:
        d.append("No version control history; the risk ranking loses change frequency, "
                 "one of its three inputs.")
    if not tests["unit"]:
        d.append("No unit test files found. Coverage measurement will be skipped; the "
                 "report proceeds with static analysis only.")
    if tests["e2e"] and not tests["unit"]:
        d.append(f"{len(tests['e2e'])} end-to-end test files exist but no unit tests. "
                 "The repository looks tested from the outside and is not. End-to-end "
                 "tests must never be reported as unit coverage.")
    if unsupported:
        d.append(f"Languages outside this version's measurement support: "
                 f"{', '.join(unsupported)}. Coverage and cyclomatic complexity are "
                 "unavailable for them; judgment-based sections still apply.")
    if not result["requirements_candidates"]:
        d.append("No requirements or specification material found; the report runs in "
                 "inference mode and carries the standing inference caveat.")
    if tests["only_markers"]:
        d.append(f"{len(tests['only_markers'])} committed `.only` marker(s) found. Each "
                 "silently disables every other test in its file. Top-tier finding.")

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

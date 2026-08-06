#!/usr/bin/env python3
"""Count dependency call sites exactly, with locations.

Requirement R-9.1 assigns deterministic work to scripts and judgment work to the model.
Counting is deterministic. Every time a report has hand-counted call sites, the count has
been wrong: one real assessment reported "20 direct browser API call sites" where the true
figure was about 30, because the model counted occurrences inside comments and missed
others. This script exists so the model never counts again.

It reports, per pattern group: total call sites, per-file counts, and every location as
`path:line`. The model's job is to interpret those numbers, not to produce them.

**Comments and string literals are stripped before matching**, so a mention of
`localStorage` in a comment is not counted as a call site. This is the single most common
source of hand-count error.

Pattern groups map onto the testability classification in SKILL.md Step 6 — these are the
dependencies that decide whether code needs a seam:

  browser_storage   localStorage / sessionStorage      -> seam type 3
  media_queries     window.matchMedia                  -> seam type 3
  clock             Date.now / new Date / timers        -> seam type 3
  randomness        Math.random / crypto.getRandomValues -> seam type 3
  network           fetch / XHR / axios / WebSocket      -> seam type 3
  filesystem        fs.* / open() / Path                 -> seam type 3
  dom               document.* / window.* mutation       -> integration-style, usually
  build_time_glob   import.meta.glob                     -> seam type 2
  env               process.env / os.environ             -> seam type 2
  process           subprocess / child_process           -> seam type 3

Usage:
    python3 census.py --repo . --json
    python3 census.py --repo . --json --group browser_storage clock
    python3 census.py --repo . --json --pattern 'supabase:\\.from\\('
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt", ".svelte-kit",
    "target", "vendor", "third_party", "coverage", "htmlcov", ".tox", "site-packages",
    ".turbo", ".cache", "out",
}

JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".svelte", ".vue")
PY_EXT = (".py",)

PY_TEST_RE = re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py)$")
JS_TEST_RE = re.compile(r".*\.(test|spec)\.(ts|tsx|js|jsx|mts|cts)$")

# Each group maps to a seam recommendation. Keep these in step with seam-catalog.md.
GROUPS: dict[str, dict] = {
    "browser_storage": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\b(localStorage|sessionStorage)\s*\.\s*(getItem|setItem|removeItem|clear|key)\b",
    },
    "media_queries": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\bwindow\s*\.\s*matchMedia\s*\(|\bmatchMedia\s*\(",
    },
    "clock": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\bDate\s*\.\s*now\s*\(|\bnew\s+Date\s*\(|\bsetTimeout\s*\(|\bsetInterval\s*\(|"
              r"\bperformance\s*\.\s*now\s*\(",
        "py": r"\bdatetime\s*\.\s*(now|today|utcnow)\s*\(|\btime\s*\.\s*(time|sleep|monotonic)\s*\(",
    },
    "randomness": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\bMath\s*\.\s*random\s*\(|\bcrypto\s*\.\s*(getRandomValues|randomUUID)\s*\(",
        "py": r"\brandom\s*\.\s*\w+\s*\(|\buuid\s*\.\s*uuid[0-9]\s*\(|\bsecrets\s*\.\s*\w+\s*\(",
    },
    "network": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\bfetch\s*\(|\bXMLHttpRequest\b|\baxios\s*\.\s*\w+\s*\(|\bnew\s+WebSocket\s*\(|"
              r"\bnew\s+EventSource\s*\(",
        "py": r"\brequests\s*\.\s*\w+\s*\(|\bhttpx\s*\.\s*\w+\s*\(|\burllib\b|\baiohttp\b",
    },
    "filesystem": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\bfs\s*\.\s*\w+\s*\(|\brequire\s*\(\s*['\"]fs['\"]\s*\)",
        "py": r"\bopen\s*\(|\bos\s*\.\s*(remove|mkdir|makedirs|listdir|rename)\s*\(|"
              r"\bshutil\s*\.\s*\w+\s*\(|\bPath\s*\([^)]*\)\s*\.\s*(read_text|write_text|open)\b",
    },
    "dom": {
        "seam": "usually integration-style rather than a catalog seam",
        "js": r"\bdocument\s*\.\s*\w+|\bwindow\s*\.\s*(addEventListener|removeEventListener|"
              r"location|open|scrollTo)\b",
    },
    "build_time_glob": {
        "seam": "2 — pass the dependency in as a parameter",
        "js": r"import\s*\.\s*meta\s*\.\s*glob\s*\(",
    },
    "env": {
        "seam": "2 — pass the dependency in as a parameter",
        "js": r"\bprocess\s*\.\s*env\b|\bimport\s*\.\s*meta\s*\.\s*env\b",
        "py": r"\bos\s*\.\s*environ\b|\bos\s*\.\s*getenv\s*\(",
    },
    "process": {
        "seam": "3 — wrap an environment boundary",
        "js": r"\bchild_process\b|\bexecSync\s*\(|\bspawnSync\s*\(",
        "py": r"\bsubprocess\s*\.\s*\w+\s*\(|\bos\s*\.\s*system\s*\(",
    },
}


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def strip_js(src: str) -> str:
    """Blank comments, strings, template literals, and regex literals, preserving offsets.

    Offsets are preserved (characters become spaces) so line numbers stay correct.
    """
    out = list(src)
    i, n = 0, len(src)
    prev = ""

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j); i = j; continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j); i = j; continue
        if c in "\"'":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2; continue
                if src[j] == c or src[j] == "\n":
                    j += 1; break
                j += 1
            blank(i, j); i = j; prev = "x"; continue
        if c == "`":
            j, depth = i + 1, 0
            blank(i, i + 1)
            while j < n:
                if src[j] == "\\":
                    blank(j, j + 2); j += 2; continue
                if src[j] == "`" and depth == 0:
                    blank(j, j + 1); j += 1; break
                if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                    d = 1
                    blank(j, j + 2); j += 2
                    while j < n and d:
                        if src[j] == "{": d += 1
                        elif src[j] == "}":
                            d -= 1
                            if not d:
                                blank(j, j + 1); j += 1; break
                        j += 1
                    continue
                blank(j, j + 1); j += 1
            i = j; prev = "x"; continue
        if c == "/" and prev not in ("x", ")", "]"):
            j, in_class = i + 1, False
            while j < n:
                if src[j] == "\\":
                    j += 2; continue
                if src[j] == "[": in_class = True
                elif src[j] == "]": in_class = False
                elif src[j] == "/" and not in_class:
                    j += 1; break
                elif src[j] == "\n":
                    break
                j += 1
            blank(i, j); i = j; prev = "x"; continue
        if not c.isspace():
            prev = "x" if (c.isalnum() or c in "_$") else c
        i += 1
    return "".join(out)


def strip_py(src: str) -> str:
    """Blank Python comments and string literals, preserving offsets."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if c == "#":
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j); i = j; continue
        if c in "\"'":
            triple = src[i:i + 3] in ('"""', "'''")
            q = src[i:i + 3] if triple else c
            j = i + len(q)
            while j < n:
                if src[j] == "\\":
                    j += 2; continue
                if src[j:j + len(q)] == q:
                    j += len(q); break
                if not triple and src[j] == "\n":
                    break
                j += 1
            blank(i, j); i = j; continue
        i += 1
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--group", nargs="*", default=None,
                    help="limit to these groups (default: all)")
    ap.add_argument("--pattern", nargs="*", default=[],
                    help="extra patterns as name:regex, e.g. 'supabase:\\.from\\('")
    ap.add_argument("--include-tests", action="store_true")
    ap.add_argument("--max-locations", type=int, default=200,
                    help="cap locations listed per group (counts stay exact)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    groups = dict(GROUPS)
    for spec in args.pattern:
        if ":" not in spec:
            print(f"error: --pattern needs name:regex, got {spec!r}", file=sys.stderr)
            return 2
        name, rx = spec.split(":", 1)
        groups[name] = {"seam": "custom", "js": rx, "py": rx}
    if args.group:
        missing = [g for g in args.group if g not in groups]
        if missing:
            print(f"error: unknown group(s): {', '.join(missing)}", file=sys.stderr)
            return 2
        groups = {k: v for k, v in groups.items() if k in args.group}

    compiled = {
        name: {
            "js": re.compile(spec["js"]) if spec.get("js") else None,
            "py": re.compile(spec["py"]) if spec.get("py") else None,
            "seam": spec.get("seam", ""),
        }
        for name, spec in groups.items()
    }

    results = {n: {"seam": c["seam"], "total": 0, "by_file": {}, "locations": []}
               for n, c in compiled.items()}
    files_scanned = tests_skipped = 0

    for path in walk(root):
        suffix = path.suffix.lower()
        if suffix in JS_EXT:
            kind = "js"
        elif suffix in PY_EXT:
            kind = "py"
        else:
            continue
        if path.name.endswith(".d.ts"):
            continue
        is_test = bool(PY_TEST_RE.match(path.name) or JS_TEST_RE.match(path.name))
        if is_test and not args.include_tests:
            tests_skipped += 1
            continue

        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        stripped = strip_js(src) if kind == "js" else strip_py(src)
        r = rel(path, root)

        # Precompute line starts once per file.
        line_starts = [0]
        for idx, ch in enumerate(stripped):
            if ch == "\n":
                line_starts.append(idx + 1)

        def line_of(pos: int) -> int:
            lo, hi = 0, len(line_starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1

        for name, c in compiled.items():
            rx = c[kind]
            if rx is None:
                continue
            for m in rx.finditer(stripped):
                entry = results[name]
                entry["total"] += 1
                entry["by_file"][r] = entry["by_file"].get(r, 0) + 1
                if len(entry["locations"]) < args.max_locations:
                    entry["locations"].append({
                        "path": r,
                        "line": line_of(m.start()),
                        "match": m.group(0).strip()[:60],
                    })

    for name, entry in results.items():
        entry["files"] = len(entry["by_file"])
        entry["by_file"] = dict(sorted(entry["by_file"].items(),
                                       key=lambda kv: -kv[1]))
        if entry["total"] > args.max_locations:
            entry["locations_truncated"] = (
                f"{entry['total']} call sites found; {args.max_locations} listed. "
                "Counts above are complete; only the location list is capped.")

    json.dump({
        "repo": str(root),
        "files_scanned": files_scanned,
        "test_files_skipped": tests_skipped,
        "basis": "exact — regex over source with comments and string literals removed",
        "note": ("These counts are deterministic and complete. Do not re-count by hand or "
                 "by eye; report these figures directly. Interpretation is the model's "
                 "job, counting is not."),
        "groups": results,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Cyclomatic complexity per function, for Python and for TypeScript or JavaScript.

Cyclomatic complexity is the number of independent paths through a function: the count
of decision points plus one. It is one of the three inputs to the risk ranking. The
per-function counts this produces are also the denominator for the report's testability
proportions, so their accuracy matters twice over.

  Python  -- always "exact". Uses the standard library `ast` module.
  TS/JS   -- "exact" when the TypeScript compiler can be resolved from the target
             repository's node_modules (see complexity_ts.js); "estimated" otherwise,
             falling back to the bundled token scanner.

The token scanner is a fallback, not the primary path. It cannot parse TypeScript: it
undercounts functions roughly threefold because it folds expression-bodied arrow
functions into their parent, and in semicolon-free source it used to invent functions
entirely. Measured against one real repository, the scanner found 338 functions in a set
of files where both the TypeScript parser and Istanbul found ~1,107.

**Never present an estimated number as a measurement.** The top-level `basis` field and
each file's `basis` field carry the distinction; the caller must carry it into the report,
including for function COUNTS derived from this output, not just complexity values.

Usage:
    python3 complexity.py --repo . --json
    python3 complexity.py --repo . --json --min 10       # only functions at or above
    python3 complexity.py --repo . --ts-from /other/repo # borrow a resolvable typescript
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt", ".svelte-kit",
    "target", "vendor", "third_party", "coverage", "htmlcov", ".tox", "site-packages",
    ".turbo", ".cache", "out",
}

PY_TEST_RE = re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py)$")
JS_TEST_RE = re.compile(r".*\.(test|spec)\.(ts|tsx|js|jsx|mts|cts)$")


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# -------------------------------------------------------------------------- python


class PyComplexity(ast.NodeVisitor):
    """Count decision points inside one function, not descending into nested ones."""

    def __init__(self) -> None:
        self.count = 0
        self._depth = 0

    def _decide(self, n: int = 1) -> None:
        self.count += n

    # Each of these introduces one independent path.
    def visit_If(self, node):  # covers elif, which the parser nests as If
        self._decide()
        self.generic_visit(node)

    def visit_For(self, node):
        self._decide()
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self._decide()
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self._decide()
        self.generic_visit(node)

    def visit_Assert(self, node):
        self._decide()
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self._decide()
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        # `a and b and c` has two short-circuit points, not one.
        self._decide(len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self._decide(len(node.ifs))
        self.generic_visit(node)

    def visit_Match(self, node):
        self._decide(len(node.cases))
        self.generic_visit(node)

    # Nested functions are measured on their own, so stop here.
    def visit_FunctionDef(self, node):
        if self._depth:
            return
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        return


def analyze_python(path: Path, root: Path) -> dict | None:
    src = read(path)
    if not src.strip():
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {"path": rel(path, root), "language": "python", "basis": "exact",
                "error": f"could not parse: {exc.msg} at line {exc.lineno}",
                "functions": []}

    functions = []

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                v = PyComplexity()
                for sub in ast.iter_child_nodes(child):
                    v.visit(sub)
                name = f"{prefix}{child.name}"
                functions.append({
                    "name": name,
                    "line": child.lineno,
                    "end_line": getattr(child, "end_lineno", child.lineno),
                    "complexity": v.count + 1,
                    "is_async": isinstance(child, ast.AsyncFunctionDef),
                })
                visit(child, prefix=f"{name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix=f"{prefix}{child.name}.")
            else:
                visit(child, prefix=prefix)

    visit(tree)
    return {
        "path": rel(path, root),
        "language": "python",
        "basis": "exact",
        "lines": src.count("\n") + 1,
        "functions": functions,
    }


# --------------------------------------------------------------------- typescript


def strip_js(src: str) -> str:
    """Blank out comments, strings, template literals, and regex literals.

    Characters are replaced with spaces rather than removed so every offset in the
    result still lines up with the original source, which keeps line numbers honest.
    """
    out = list(src)
    i, n = 0, len(src)
    # Tracks whether a `/` begins a regex literal or is a division operator. After a
    # value (identifier, number, closing bracket) it is division; otherwise a regex.
    prev_significant = ""

    def blank(start: int, end: int) -> None:
        for k in range(start, min(end, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]

        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
            continue

        if c in "\"'":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c or src[j] == "\n":
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
            prev_significant = "x"
            continue

        if c == "`":
            # Template literal. Interpolations hold real code, so keep them.
            j = i + 1
            blank(i, i + 1)
            while j < n:
                if src[j] == "\\":
                    blank(j, j + 2)
                    j += 2
                    continue
                if src[j] == "`":
                    blank(j, j + 1)
                    j += 1
                    break
                if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                    depth = 1
                    blank(j, j + 2)
                    j += 2
                    while j < n and depth:
                        if src[j] == "{":
                            depth += 1
                        elif src[j] == "}":
                            depth -= 1
                            if not depth:
                                blank(j, j + 1)
                                j += 1
                                break
                        j += 1
                    continue
                blank(j, j + 1)
                j += 1
            i = j
            prev_significant = "x"
            continue

        if c == "/" and prev_significant not in ("x", ")", "]"):
            j = i + 1
            in_class = False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    j += 1
                    break
                elif src[j] == "\n":
                    break
                j += 1
            blank(i, j)
            i = j
            prev_significant = "x"
            continue

        if not c.isspace():
            prev_significant = "x" if (c.isalnum() or c in "_$") else c
        i += 1

    return "".join(out)


# Words that look like a call followed by a block but are not function declarations.
NOT_A_FUNCTION = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "instanceof", "in",
    "of", "new", "delete", "void", "await", "yield", "do", "else", "try", "finally",
    "import", "export", "as", "from", "case", "default", "with",
}

FUNC_PATTERNS = [
    # function foo(...)  /  function* foo(...)  /  function(...)
    re.compile(r"\bfunction\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)?\s*(?=\()"),
    # const foo = ... -- whether this is actually an arrow function is decided by
    # arrow_body_start() below, not by the regex. A lookahead cannot do it: source
    # written without semicolons has no statement terminator to bound the search, so
    # a lookahead scanning for "=>" runs past the end of the statement and matches an
    # unrelated arrow further down the file, inventing functions that do not exist.
    re.compile(r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
               r"(?::[^=;\n]+)?=(?P<after>)"),
    # class methods and object methods:  name(...) {   /   async name(...) {
    re.compile(r"(?:^|[{;}\n])\s*(?:public\s+|private\s+|protected\s+|static\s+|"
               r"async\s+|get\s+|set\s+|\*\s*)*(?P<name>[A-Za-z_$][\w$]*)\s*"
               r"(?=\([^)]*\)\s*(?::[^{;]+)?\{)"),
]


def arrow_body_start(text: str, i: int) -> int:
    """Decide whether a brace-bodied arrow function begins at index i.

    Returns the index of the body's opening brace, or -1. Walks the actual tokens --
    optional `async`, then either a parenthesized parameter list (paren-matched) or a
    single identifier, then an optional return-type annotation, then `=>` -- instead of
    guessing with a regex lookahead.
    """
    n = len(text)

    def skip_ws(j: int) -> int:
        while j < n and text[j].isspace():
            j += 1
        return j

    i = skip_ws(i)
    if text.startswith("async", i) and (i + 5 >= n or not (text[i + 5].isalnum()
                                                           or text[i + 5] in "_$")):
        i = skip_ws(i + 5)

    if i < n and text[i] == "(":
        depth = 0
        while i < n:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        else:
            return -1
    elif i < n and (text[i].isalpha() or text[i] in "_$"):
        while i < n and (text[i].isalnum() or text[i] in "_$"):
            i += 1
    else:
        return -1

    i = skip_ws(i)
    if i < n and text[i] == ":":
        # Return-type annotation. Scan for the arrow, giving up at any token that
        # proves this is not an arrow function.
        limit = min(n, i + 200)
        while i < limit:
            if text.startswith("=>", i):
                break
            if text[i] in ";{}":
                return -1
            i += 1
        else:
            return -1

    if not text.startswith("=>", i):
        return -1
    i = skip_ws(i + 2)
    return i if i < n and text[i] == "{" else -1

DECISION_RE = re.compile(
    r"\b(if|for|while|case|catch)\b"          # branching keywords
    r"|&&|\|\|"                                # short-circuit operators
    r"|\?\?(?!=)"                              # nullish coalescing, not ??=
    r"|(?<![?.\w])\?(?![?.:])"                 # ternary, not ?. ?? or optional param
)


def _match_braces(text: str, open_idx: int) -> int:
    """Index just past the `}` matching the `{` at open_idx, or len(text)."""
    depth, i, n = 0, open_idx, len(text)
    while i < n:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def analyze_js(path: Path, root: Path) -> dict | None:
    src = read(path)
    if not src.strip():
        return None
    stripped = strip_js(src)

    # Locate function bodies as (start, end, name), then assign each decision point to
    # the innermost body containing it.
    bodies: list[tuple[int, int, str]] = []
    seen_starts: set[int] = set()

    for pattern_index, pattern in enumerate(FUNC_PATTERNS):
        for m in pattern.finditer(stripped):
            name = m.group("name") or "<anonymous>"
            if name in NOT_A_FUNCTION:
                continue

            if pattern_index == 1:
                # `const name = ...` -- only an arrow function with a brace body counts.
                brace = arrow_body_start(stripped, m.end())
            else:
                # Walk forward to the body's opening brace, past params and return types.
                j, depth, brace = m.end(), 0, -1
                limit = min(len(stripped), j + 2000)
                while j < limit:
                    ch = stripped[j]
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                    elif ch == "{" and depth <= 0:
                        brace = j
                        break
                    elif ch == ";" and depth <= 0:
                        break
                    j += 1

            if brace < 0 or brace in seen_starts:
                continue
            seen_starts.add(brace)
            end = _match_braces(stripped, brace)
            bodies.append((brace, end, name))

    line_of = [0] * (len(stripped) + 1)
    line = 1
    for idx, ch in enumerate(stripped):
        line_of[idx] = line
        if ch == "\n":
            line += 1
    line_of[len(stripped)] = line

    counts: dict[int, int] = {i: 0 for i in range(len(bodies))}
    file_decisions = 0
    for m in DECISION_RE.finditer(stripped):
        pos = m.start()
        file_decisions += 1
        innermost, best_span = None, None
        for idx, (s, e, _) in enumerate(bodies):
            if s <= pos < e:
                span = e - s
                if best_span is None or span < best_span:
                    innermost, best_span = idx, span
        if innermost is not None:
            counts[innermost] += 1

    functions = [
        {
            "name": name,
            "line": line_of[s],
            "end_line": line_of[min(e, len(stripped))],
            "complexity": counts[idx] + 1,
        }
        for idx, (s, e, name) in enumerate(bodies)
    ]
    functions.sort(key=lambda f: f["line"])

    return {
        "path": rel(path, root),
        "language": "typescript" if path.suffix in (".ts", ".tsx", ".mts", ".cts")
                    else "javascript",
        "basis": "estimated",
        "basis_note": ("Token-based estimate, not a real parse. Arrow functions with "
                       "expression bodies are folded into their enclosing function."),
        "lines": src.count("\n") + 1,
        "file_complexity": file_decisions + 1,
        "functions": functions,
    }


# ---------------------------------------------------------------------------- main


def run_ts_parser(root: Path, rel_files: list[str], ts_from: str | None) -> list[dict] | None:
    """Parse TS/JS with the real TypeScript compiler. None if unavailable.

    Resolution comes from the target repository's own node_modules, so nothing is
    installed. A repository whose dependencies are not installed cannot be parsed, which
    is a real limitation and must surface as a degradation rather than being papered over.
    """
    script = Path(__file__).with_name("complexity_ts.js")
    if not script.is_file() or not rel_files:
        return None
    cmd = ["node", str(script), "--repo", str(ts_from or root)]
    try:
        p = subprocess.run(cmd, input="\n".join(rel_files), capture_output=True,
                           text=True, timeout=300, cwd=str(root))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)["files"]
    except (ValueError, KeyError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--min", type=int, default=0,
                    help="only report functions with complexity at or above this")
    ap.add_argument("--include-tests", action="store_true",
                    help="also measure test files (off by default)")
    ap.add_argument("--ts-from", default=None,
                    help="resolve the typescript package from this path instead of --repo, "
                         "for repositories whose dependencies are not installed")
    ap.add_argument("--force-token-scan", action="store_true",
                    help="skip the parser and use the estimating fallback (for comparison)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    # Collect candidates first so TS/JS can go to the parser in one batch.
    py_paths, js_rel, skipped_tests = [], [], 0
    for path in walk(root):
        suffix = path.suffix.lower()
        is_test = bool(PY_TEST_RE.match(path.name) or JS_TEST_RE.match(path.name))
        if is_test and not args.include_tests:
            skipped_tests += 1
            continue
        if suffix == ".py":
            py_paths.append(path)
        elif suffix in (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"):
            if path.name.endswith(".d.ts"):
                continue
            js_rel.append(rel(path, root))

    files = [r for r in (analyze_python(p, root) for p in py_paths) if r]

    ts_basis, ts_note = None, None
    parsed = None if args.force_token_scan else run_ts_parser(root, js_rel, args.ts_from)
    if parsed is not None:
        files.extend(parsed)
        ts_basis = "exact"
    elif js_rel:
        # Fallback: the token scanner. Estimated, and the caller must say so.
        for r in js_rel:
            result = analyze_js(root / r, root)
            if result:
                files.append(result)
        ts_basis = "estimated"
        ts_note = ("The TypeScript compiler could not be resolved from the target "
                   "repository (its dependencies are probably not installed), so "
                   "TypeScript and JavaScript figures come from the token scanner. "
                   "Function counts from that scanner run roughly threefold low. Treat "
                   "every TS/JS complexity value AND function count as an estimate.")

    if args.min:
        for f in files:
            f["functions"] = [fn for fn in f["functions"]
                              if fn["complexity"] >= args.min]

    all_fns = [(f["path"], fn) for f in files for fn in f["functions"]]
    all_fns.sort(key=lambda pair: -pair[1]["complexity"])

    parse_errors = [f["path"] for f in files if f.get("error")]

    ts_desc = {"exact": "exact (TypeScript compiler API)",
               "estimated": "ESTIMATED (token scan fallback; counts run ~3x low)",
               None: "not applicable (no TS/JS files)"}[ts_basis]

    out = {
        "repo": str(root),
        "files_measured": len(files),
        "test_files_skipped": skipped_tests,
        "functions_measured": len(all_fns),
        # Both complexity values and FUNCTION COUNTS inherit this basis. Reports have
        # repeatedly labelled the counts "measured" while labelling complexity
        # "estimated"; they come from the same pass and share the same confidence.
        "basis_by_language": {
            "python": "exact (ast module)",
            "typescript/javascript": ts_desc,
        },
        "counts_are_exact": (ts_basis != "estimated"),
        "parse_errors": parse_errors,
        "hotspots": [
            {"path": p, **fn} for p, fn in all_fns[:40]
        ],
        "files": files,
    }
    if ts_note:
        out.setdefault("degradations", []).append(ts_note)
    if parse_errors:
        out.setdefault("degradations", []).append(
            f"{len(parse_errors)} file(s) could not be parsed; their complexity is absent "
            "rather than zero.")

    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

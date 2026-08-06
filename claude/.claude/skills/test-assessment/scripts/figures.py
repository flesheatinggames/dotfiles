#!/usr/bin/env python3
"""Consolidate every analyser's output into one canonical list of the report's figures.

Requirement R-7.3 (amended): every numeric figure in the report comes from one generated
source, so that recomputing anything cannot leave superseded numbers standing in prose while
the tables carry corrected ones.

The failure this prevents is concrete rather than hypothetical. One validation report
retained token-scanner figures in its recommendation prose after an analyser correction
recomputed every figure in its tables, so the same report stated two different function
counts and only the tables were right. Two copies of a number drift, and the copy in prose
is the one a reader quotes.

What it does:

1. Runs (or reads) each analyser: detect_env, complexity, census, churn, parse_coverage.
2. Derives the report's headline figures from them, each carrying its measured-or-estimated
   basis and the exact command that produced it.
3. Reads the report's existing index block, where one exists, and records any figure whose
   value changed as `superseded`, so `check_index.py` can fail a report that still quotes
   the old number.

The basis is not decided here in any interesting sense — it is read off the analyser. The
only real judgment is `complexity.py`'s `counts_are_exact`, which governs whether TypeScript
and JavaScript complexity *and function counts* are measurements or estimates. They share
one pass, and reports have repeatedly labelled the first correctly and the second as
measured.

Usage:
    python3 figures.py --repo . --json
    python3 figures.py --repo . --report docs/test-assessment.md --json
    python3 figures.py --repo . --coverage /tmp/cov.json --json
    python3 figures.py --repo . --coverage-file coverage/lcov.info --json
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_INFO_STRING = "json assessment-index"

# The command as it should appear in the report's reproduction block: skill location as a
# variable, repository as a dot. R-5.2 forbids absolute paths in a fenced block, and a
# `note` field that quotes one would put the defect back in a different place.
SKILL_VARIABLE = "$SKILL"


class Analyser:
    """One analyser's output plus how it was obtained."""

    def __init__(self, name, command, data, error=None):
        self.name = name
        self.command = command
        self.data = data
        self.error = error

    @property
    def ok(self):
        return self.data is not None and self.error is None


def run_analyser(name, argv, repo, timeout=300):
    """Run one bundled analyser and parse its JSON.

    A failure here is recorded and carried into the output rather than raised. The skill's
    rule is degrade rather than fail: a repository with no version control history has no
    churn figures, and that is a degradation to state, not a reason to produce no figures at
    all.
    """
    display = " ".join([f"python3 {SKILL_VARIABLE}/{name}.py"] + argv)
    command = [sys.executable, os.path.join(HERE, f"{name}.py")] + argv
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, cwd=repo
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Analyser(name, display, None, f"could not run: {error}")
    if not finished.stdout.strip():
        detail = (finished.stderr or "").strip().splitlines()
        return Analyser(
            name, display, None, detail[-1] if detail else "produced no output"
        )
    try:
        return Analyser(name, display, json.loads(finished.stdout))
    except json.JSONDecodeError as error:
        return Analyser(name, display, None, f"output was not JSON: {error}")


def load_analyser(name, path, command):
    """Read an analyser's output that the caller already produced."""
    try:
        with open(path, encoding="utf-8") as handle:
            return Analyser(name, command, json.load(handle))
    except (OSError, json.JSONDecodeError) as error:
        return Analyser(name, command, None, f"could not read {path}: {error}")


# --------------------------------------------------------------------------------------
# Deriving the figures
# --------------------------------------------------------------------------------------


class Figures:
    def __init__(self):
        self.metrics = []
        self._by_name = {}

    def add(self, name, value, basis, note, command):
        """Record one figure. A duplicate name is a bug in this script, not in the report."""
        if name in self._by_name:
            raise ValueError(f"figure {name!r} derived twice")
        metric = {
            "name": name,
            "value": value,
            "basis": basis,
            "note": note,
            "command": command,
        }
        self.metrics.append(metric)
        self._by_name[name] = metric

    def get(self, name):
        return self._by_name.get(name)


def derive_complexity(figures, analyser):
    """Function counts, file counts, and total complexity — all from one pass.

    `counts_are_exact` governs all three together. This is the single most repeated defect in
    this skill's output: the complexity value gets labelled correctly and the function count
    beside it gets labelled `measured`, when the same token scanner produced both and
    undercounts functions roughly threefold.
    """
    if not analyser.ok:
        return
    data = analyser.data
    exact = bool(data.get("counts_are_exact"))
    basis = "measured" if exact else "estimated"

    languages = sorted(
        {entry.get("language") for entry in data.get("files") or [] if entry.get("language")}
    )
    if exact:
        note = (
            "Real parser (TypeScript compiler interface, or Python's ast). Exact. "
            f"Languages: {', '.join(languages) or 'none'}."
        )
    else:
        note = (
            "Token-scanner fallback: no language parser could be resolved from the target "
            "repository, usually because its dependencies are not installed. Function counts "
            "are undercounted by roughly threefold and complexity is approximate. "
            f"Languages: {', '.join(languages) or 'none'}."
        )

    figures.add(
        "production_files", data.get("files_measured"), "measured",
        "Files walked on the filesystem, which is exact regardless of the parser.",
        analyser.command,
    )
    figures.add(
        "production_functions", data.get("functions_measured"), basis, note, analyser.command
    )
    total = sum(
        entry.get("file_complexity") or 0 for entry in data.get("files") or []
    )
    figures.add("production_complexity", total, basis, note, analyser.command)


def derive_env(figures, analyser):
    """Test file counts, from the filesystem, so always exact."""
    if not analyser.ok:
        return
    tests = analyser.data.get("tests") or {}
    counts = tests.get("counts") or {}

    unit = len(tests.get("unit") or [])
    integration = len(tests.get("integration") or [])
    e2e = len(tests.get("e2e") or [])

    figures.add(
        "test_files", unit + integration, "measured",
        "Unit and integration test files found on the filesystem. End-to-end files are "
        "counted separately and never substitute for unit coverage.",
        analyser.command,
    )
    figures.add(
        "e2e_test_files", e2e, "measured",
        "Playwright or Cypress files. A repository with a large end-to-end suite and no unit "
        "tests looks tested from the outside and is not.",
        analyser.command,
    )
    figures.add(
        "skipped_test_cases", len(tests.get("skipped") or []), "measured",
        "Tests carrying a skip, todo, or expected-failure marker. Silent subtractions from "
        "real coverage.",
        analyser.command,
    )
    if tests.get("only_markers"):
        figures.add(
            "only_markers", len(tests["only_markers"]), "measured",
            "Committed `.only` markers. Each one silently disables every other test in its "
            "file while the suite reports green.",
            analyser.command,
        )
    for kind in ("unit", "integration", "e2e"):
        if counts.get(kind):
            figures.add(
                f"{kind}_test_cases_detected", counts[kind], "measured",
                f"Test cases the {kind} detection counted. The runner's own count is "
                "authoritative where a suite runs; this is the static count.",
                analyser.command,
            )


def derive_census(figures, analyser):
    """Dependency call sites, per category. Always exact — this is what census.py is for.

    Hand-counting these is the second recurring defect: one report claimed twenty browser API
    call sites where the true figure was thirty-seven.
    """
    if not analyser.ok:
        return
    groups = analyser.data.get("groups") or {}
    for name in sorted(groups):
        group = groups[name] or {}
        total = group.get("total") or 0
        if not total:
            continue
        figures.add(
            f"census_{name}", total, "measured",
            f"Call sites in category {name!r} ({group.get('seam', 'no seam mapping')}), "
            "counted with comments and string literals stripped.",
            analyser.command,
        )


def derive_churn(figures, analyser):
    if not analyser.ok or not analyser.data.get("available"):
        return
    data = analyser.data
    figures.add(
        "commits_scanned", data.get("commits_scanned"), "measured",
        f"Commits read from version control history ({data.get('since', 'all history')}).",
        analyser.command,
    )
    figures.add(
        "files_tracked", data.get("files_tracked"), "measured",
        "Files with version control history, which is the denominator of the churn input to "
        "the risk ranking.",
        analyser.command,
    )


def derive_coverage(figures, analyser):
    if not analyser.ok:
        return
    totals = analyser.data.get("totals") or {}
    note = (
        f"Parsed from {analyser.data.get('format', 'unknown')} output. Coverage numbers are "
        "not comparable across configurations."
    )
    if totals.get("line_pct") is not None:
        figures.add("coverage_line_pct", totals["line_pct"], "measured", note, analyser.command)
    if totals.get("branch_pct") is not None:
        figures.add(
            "coverage_branch_pct", totals["branch_pct"], "measured", note, analyser.command
        )
    elif analyser.data.get("branch_coverage_available") is False:
        # Deliberately emits nothing. Absent branch data and zero branch coverage are
        # different facts, and a zero here would be read as the second.
        pass
    if totals.get("files") is not None:
        figures.add(
            "instrumented_files", totals["files"], "measured",
            note + " Counts only files the coverage run instrumented, which may be narrower "
            "than the repository.",
            analyser.command,
        )
    for key, name in (
        ("lines_total", "instrumented_lines"),
        ("lines_covered", "covered_lines"),
    ):
        if totals.get(key) is not None:
            figures.add(name, totals[key], "measured", note, analyser.command)


# --------------------------------------------------------------------------------------
# Superseded values
# --------------------------------------------------------------------------------------


def read_index_metrics(report_path):
    """The metrics from the report's existing index block, keyed by name.

    Returns an empty mapping when there is no report, no index, or an index this cannot
    parse. A first run has nothing to supersede, and a malformed index is `check_index.py`'s
    problem to report rather than this script's to fail over.
    """
    try:
        text = open(report_path, encoding="utf-8").read()
    except OSError:
        return {}

    body = extract_index_block(text)
    if body is None:
        return {}
    try:
        index = json.loads(body)
    except json.JSONDecodeError:
        return {}
    if not isinstance(index, dict):
        return {}
    return {
        m["name"]: m
        for m in index.get("metrics") or []
        if isinstance(m, dict) and isinstance(m.get("name"), str)
    }


def extract_index_block(text):
    """The body of the single ```json assessment-index``` fence, or None.

    Fence tracking matches `check_index.py`: a closing fence must be at least as long as the
    one that opened it, so a four-backtick fence containing three-backtick fences works.
    """
    fence_re = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
    fence_char = None
    fence_len = 0
    fence_info = None
    buffer = []
    for line in text.splitlines():
        match = fence_re.match(line)
        if fence_char is None:
            if match:
                fence_char = match.group(2)[0]
                fence_len = len(match.group(2))
                fence_info = match.group(3).strip()
                buffer = []
            continue
        if (
            match
            and match.group(2)[0] == fence_char
            and len(match.group(2)) >= fence_len
            and match.group(3).strip() == ""
        ):
            if fence_info == INDEX_INFO_STRING:
                return "\n".join(buffer)
            fence_char = None
            fence_info = None
            buffer = []
            continue
        buffer.append(line)
    return None


def apply_supersession(figures, previous):
    """Carry a changed figure's old value forward as `superseded`.

    Only a *changed* value supersedes. Re-running the analysers with nothing altered must
    not accumulate a growing list of the same number, or the check that no superseded value
    appears in prose would eventually fire on the current one.
    """
    changed = []
    for metric in figures.metrics:
        old = previous.get(metric["name"])
        if not old:
            continue
        carried = [v for v in (old.get("superseded") or []) if isinstance(v, (int, float))]
        if old.get("value") != metric["value"] and isinstance(old.get("value"), (int, float)):
            carried.append(old["value"])
            changed.append(
                {
                    "name": metric["name"],
                    "was": old["value"],
                    "now": metric["value"],
                    "was_basis": old.get("basis"),
                    "now_basis": metric["basis"],
                }
            )
        # Deduplicate while preserving order: a value that was superseded, restored, and
        # superseded again is one fact, not two.
        seen = []
        for value in carried:
            if value not in seen and value != metric["value"]:
                seen.append(value)
        if seen:
            metric["superseded"] = seen
    return changed


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def collect(args):
    repo = os.path.abspath(args.repo)
    analysers = {}

    if args.complexity:
        analysers["complexity"] = load_analyser(
            "complexity", args.complexity, f"python3 {SKILL_VARIABLE}/complexity.py --repo . --json"
        )
    else:
        analysers["complexity"] = run_analyser("complexity", ["--repo", ".", "--json"], repo)

    if args.env:
        analysers["detect_env"] = load_analyser(
            "detect_env", args.env, f"python3 {SKILL_VARIABLE}/detect_env.py --repo . --json"
        )
    else:
        analysers["detect_env"] = run_analyser("detect_env", ["--repo", ".", "--json"], repo)

    if args.census:
        analysers["census"] = load_analyser(
            "census", args.census, f"python3 {SKILL_VARIABLE}/census.py --repo . --json"
        )
    else:
        analysers["census"] = run_analyser("census", ["--repo", ".", "--json"], repo)

    if args.churn:
        analysers["churn"] = load_analyser(
            "churn", args.churn, f"python3 {SKILL_VARIABLE}/churn.py --repo . --json"
        )
    else:
        analysers["churn"] = run_analyser("churn", ["--repo", ".", "--json"], repo)

    if args.coverage:
        analysers["coverage"] = load_analyser(
            "coverage",
            args.coverage,
            f"python3 {SKILL_VARIABLE}/parse_coverage.py <coverage file> --json",
        )
    elif args.coverage_file:
        analysers["coverage"] = run_analyser(
            "parse_coverage", [args.coverage_file, "--json"], repo
        )
    else:
        analysers["coverage"] = Analyser(
            "coverage", None, None, "no coverage output was supplied"
        )

    figures = Figures()
    derive_complexity(figures, analysers["complexity"])
    derive_env(figures, analysers["detect_env"])
    derive_census(figures, analysers["census"])
    derive_churn(figures, analysers["churn"])
    derive_coverage(figures, analysers["coverage"])

    changed = []
    if args.report:
        changed = apply_supersession(figures, read_index_metrics(args.report))

    degradations = [
        {"analyser": a.name, "reason": a.error}
        for a in analysers.values()
        if a.error and a.name != "coverage"
    ]
    if analysers["coverage"].error:
        degradations.append(
            {
                "analyser": "coverage",
                "reason": analysers["coverage"].error
                + ". The report must state that no coverage exists rather than printing "
                "zeros that look like measurements.",
            }
        )

    return {
        "repo": repo,
        "report": args.report,
        "metrics": figures.metrics,
        "changed_since_index": changed,
        "degradations": degradations,
        "estimated": [m["name"] for m in figures.metrics if m["basis"] == "estimated"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("--report", help="existing report, read to carry superseded values forward")
    parser.add_argument("--complexity", help="pre-computed complexity.py --json output")
    parser.add_argument("--env", help="pre-computed detect_env.py --json output")
    parser.add_argument("--census", help="pre-computed census.py --json output")
    parser.add_argument("--churn", help="pre-computed churn.py --json output")
    parser.add_argument("--coverage", help="pre-computed parse_coverage.py --json output")
    parser.add_argument("--coverage-file", help="raw coverage file, parsed with parse_coverage.py")
    parser.add_argument("--json", action="store_true", help="emit the figures as JSON")
    args = parser.parse_args()

    result = collect(args)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"{len(result['metrics'])} figures from {result['repo']}\n")
    width = max((len(m["name"]) for m in result["metrics"]), default=0)
    for metric in result["metrics"]:
        mark = " " if metric["basis"] == "measured" else "~"
        line = f"  {mark} {metric['name']:<{width}}  {metric['value']}"
        if metric.get("superseded"):
            line += "   (was " + ", ".join(str(v) for v in metric["superseded"]) + ")"
        print(line)

    if result["estimated"]:
        print(
            "\n  ~ marks an estimate. Every one of these must carry its qualifier wherever it "
            "appears in the report, including the executive summary and the findings table."
        )
    if result["changed_since_index"]:
        print("\n  Changed since the report's index:")
        for change in result["changed_since_index"]:
            print(f"    {change['name']}: {change['was']} -> {change['now']}")
        print(
            "    Every one of these old values must be gone from the prose. check_index.py "
            "fails the report on any that remain."
        )
    if result["degradations"]:
        print("\n  Degradations to record in the report:")
        for degradation in result["degradations"]:
            print(f"    {degradation['analyser']}: {degradation['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

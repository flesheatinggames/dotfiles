#!/usr/bin/env python3
"""Change frequency per file, from version control history.

Change frequency is the second of the three risk-ranking inputs. Code that changes often
and is not verified is riskier than code that is equally complex but has been stable for
years, because every change is an opportunity for a regression that nothing catches.

Reads git history only. Writes nothing and checks nothing out.

If the repository has no git history, this exits successfully with `available: false`.
The caller must then record in the report that the risk ranking used two of its three
inputs rather than silently ranking on the remaining two as though nothing were missing.

Usage:
    python3 churn.py --repo . --json
    python3 churn.py --repo . --json --since "18 months ago"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

SKIP_PREFIXES = (
    "node_modules/", ".venv/", "venv/", "vendor/", "third_party/", "dist/", "build/",
    ".next/", "coverage/", "htmlcov/", "target/", "site-packages/", ".turbo/",
)

CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".go", ".rs",
                 ".java", ".rb", ".php", ".cs", ".kt", ".swift", ".c", ".cc", ".cpp",
                 ".h", ".hpp", ".svelte", ".vue")


def git(repo: Path, *args: str, timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "git executable not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"git timed out after {timeout}s"


def interesting(path: str) -> bool:
    if path.startswith(SKIP_PREFIXES):
        return False
    return path.endswith(CODE_SUFFIXES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--since", default="", help='e.g. "18 months ago"; default is all history')
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()

    code, out, err = git(repo, "rev-parse", "--is-inside-work-tree", timeout=args.timeout)
    if code != 0 or out.strip() != "true":
        json.dump({
            "repo": str(repo),
            "available": False,
            "reason": (err.strip() or "not a git repository"),
            "degradation": ("No version control history available. The risk ranking loses "
                            "change frequency, one of its three inputs, and must say so."),
            "files": [],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # `git log --name-only` prints paths relative to the repository root, while
    # `git ls-files` prints them relative to the working directory. When the analyzed
    # directory is nested inside a larger repository -- a workspace package, or an app
    # in a monorepo -- those two forms never match and every file is silently dropped.
    # Normalize both to repository-root-relative, then scope to the subdirectory.
    _, prefix_out, _ = git(repo, "rev-parse", "--show-prefix", timeout=args.timeout)
    prefix = prefix_out.strip()

    log_args = ["log", "--no-merges", "--pretty=format:%H%x09%aI%x09%aE", "--name-only"]
    if args.since:
        log_args.insert(1, f"--since={args.since}")
    if prefix:
        # Restrict history to this subdirectory so churn reflects this project only.
        log_args += ["--", "."]

    code, out, err = git(repo, *log_args, timeout=args.timeout)
    if code != 0:
        json.dump({
            "repo": str(repo),
            "available": False,
            "reason": err.strip() or f"git log failed with code {code}",
            "degradation": ("Version control history could not be read. The risk ranking "
                            "loses change frequency, one of its three inputs."),
            "files": [],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    commits = 0
    counts: dict[str, int] = defaultdict(int)
    authors: dict[str, set] = defaultdict(set)
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}

    cur_date, cur_author = "", ""
    for line in out.splitlines():
        if not line.strip():
            continue
        if "\t" in line and line.count("\t") >= 2:
            _, cur_date, cur_author = line.split("\t", 2)
            commits += 1
            continue
        path = line.strip()
        # Reduce repository-root-relative paths to paths relative to the analyzed
        # directory, discarding anything outside it.
        if prefix:
            if not path.startswith(prefix):
                continue
            path = path[len(prefix):]
        if not interesting(path):
            continue
        counts[path] += 1
        authors[path].add(cur_author)
        # git log is newest-first, so the first sighting is the most recent change.
        last_seen.setdefault(path, cur_date)
        first_seen[path] = cur_date

    # Only rank files that still exist; deleted files are history, not risk.
    code, tracked_out, _ = git(repo, "ls-files", timeout=args.timeout)
    tracked = {p for p in tracked_out.splitlines() if p.strip()}

    files = [
        {
            "path": p,
            "commits": n,
            "authors": len(authors[p]),
            "first_change": first_seen.get(p),
            "last_change": last_seen.get(p),
            "exists": p in tracked,
        }
        for p, n in counts.items()
    ]
    live = [f for f in files if f["exists"]]
    live.sort(key=lambda f: (-f["commits"], f["path"]))

    max_commits = live[0]["commits"] if live else 0
    for f in live:
        # Normalized 0..1 so the ranking script can combine it with complexity.
        f["churn_score"] = round(f["commits"] / max_commits, 4) if max_commits else 0.0

    json.dump({
        "repo": str(repo),
        "available": True,
        "since": args.since or "all history",
        "commits_scanned": commits,
        "files_tracked": len(live),
        "files_deleted_ignored": len(files) - len(live),
        "top": live[:40],
        "files": live,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

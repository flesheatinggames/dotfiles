#!/usr/bin/env python3
"""Combine complexity, change frequency, and coverage into a risk ranking.

Requirement R-6.9.1: findings are ranked by risk, not by coverage percentage, and the
ranking method must be stated so a reader can disagree with it. This script computes the
mechanical part. The model still decides what the ranking means and may override an
individual placement -- but it must say when it does, and why.

The method, stated plainly:

    risk = 0.40 * complexity + 0.35 * (1 - verification) + 0.25 * churn

  complexity    Highest cyclomatic complexity in the file, normalized against the most
                complex file in the repository. Complex code has more paths to get wrong.
  verification  Fraction of the file's lines covered by tests, 0 to 1. The term is
                inverted, so unverified code scores higher. When the model has judged a
                file covered-but-not-meaningfully-verified, pass --unverified with those
                paths and their coverage is treated as zero, because coverage that does
                not verify is not verification.
  churn         Commits touching the file, normalized against the most-changed file.
                Frequently changed code gets more chances to break.

Every input is normalized to 0..1 against the repository's own maximum, so the score is
relative to this codebase and is not comparable across repositories.

When an input is unavailable, its weight is redistributed across the remaining inputs
rather than being treated as zero -- a missing measurement is not a low score. The output
records which inputs were used.

Usage:
    python3 rank.py --complexity cx.json --churn churn.json --coverage cov.json --json
    python3 rank.py --complexity cx.json --unverified src/a.ts src/b.ts --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEIGHTS = {"complexity": 0.40, "verification": 0.35, "churn": 0.25}


def load(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        print(f"warning: {p} does not exist; continuing without it", file=sys.stderr)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        print(f"warning: {p} is not valid JSON ({exc}); continuing without it",
              file=sys.stderr)
        return None


def normalize_path(p: str, repo_root: Path | None = None) -> str:
    """Reduce a path to one relative to the repository root.

    Coverage tools emit absolute paths while complexity and churn emit relative ones, so
    the three sources must be brought to a common form before they can be joined. Only
    absolute paths are rewritten -- a relative path is already in the target form, and
    trimming it further would silently merge `src/lib/x.ts` with `app/lib/x.ts`.
    """
    p = p.replace("\\", "/").lstrip("./")
    if not p.startswith("/"):
        return p
    if repo_root:
        root = str(repo_root).replace("\\", "/").rstrip("/") + "/"
        if p.startswith(root):
            return p[len(root):]
    return p


def suffix_match(target: str, candidates: set[str]) -> str | None:
    """Fall back to the longest path suffix shared with a known file.

    Needed when a coverage report was produced from a different working directory than
    the one being analyzed, so its absolute paths do not share the repository root.
    """
    if target in candidates:
        return target
    best, best_len = None, 0
    tparts = target.split("/")
    for cand in candidates:
        cparts = cand.split("/")
        n = 0
        while n < len(tparts) and n < len(cparts) and tparts[-1 - n] == cparts[-1 - n]:
            n += 1
        if n > best_len and n >= 2:
            best, best_len = cand, n
    return best


def assign_tiers(rows: list[dict]) -> None:
    """Assign tiers by position within this repository, not by absolute score.

    Absolute thresholds collapse in the two cases that matter most. A repository with no
    tests puts every file above the threshold, and a well-tested one puts every file
    below it; both produce a ranking that discriminates nothing. Tiers are therefore
    relative: the top tenth, the next fifth, the next third, the rest.

    A floor still applies, so a genuinely low-risk file is never called top tier merely
    for being the worst of a good set. Tiers are relative to this repository and mean
    nothing across repositories -- the risk_score is the comparable number.
    """
    n = len(rows)
    if not n:
        return
    top_cut = max(1, round(n * 0.10))
    high_cut = top_cut + max(1, round(n * 0.20))
    med_cut = high_cut + max(1, round(n * 0.30))
    for i, r in enumerate(rows):
        if i < top_cut:
            tier = "top"
        elif i < high_cut:
            tier = "high"
        elif i < med_cut:
            tier = "medium"
        else:
            tier = "low"
        # Absolute floors: a file cannot be called top tier on rank alone.
        if tier == "top" and r["risk_score"] < 0.35:
            tier = "high"
        if tier in ("top", "high") and r["risk_score"] < 0.20:
            tier = "medium"
        r["tier"] = tier


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--complexity", help="output of complexity.py")
    ap.add_argument("--churn", help="output of churn.py")
    ap.add_argument("--coverage", help="output of parse_coverage.py")
    ap.add_argument("--unverified", nargs="*", default=[],
                    help="paths the model judged covered-but-not-meaningfully-verified; "
                         "their coverage is treated as zero")
    ap.add_argument("--repo", help="repository root, used to make coverage paths relative")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve() if args.repo else None
    cx = load(args.complexity)
    ch = load(args.churn)
    cv = load(args.coverage)
    if repo_root is None and cx and cx.get("repo"):
        repo_root = Path(cx["repo"])

    available, degradations = [], []

    # ---- complexity
    cx_by_file: dict[str, dict] = {}
    if cx and cx.get("files"):
        available.append("complexity")
        for f in cx["files"]:
            fns = f.get("functions") or []
            peak = max((fn["complexity"] for fn in fns), default=1)
            cx_by_file[normalize_path(f["path"], repo_root)] = {
                "max_complexity": peak,
                "total_complexity": sum(fn["complexity"] for fn in fns),
                "functions": len(fns),
                "basis": f.get("basis", "unknown"),
                "worst_function": max(fns, key=lambda fn: fn["complexity"])["name"]
                                  if fns else None,
            }
    else:
        degradations.append(
            "Cyclomatic complexity unavailable; its weight was redistributed across the "
            "remaining inputs. The ranking is weaker as a result.")

    # ---- churn
    ch_by_file: dict[str, dict] = {}
    if ch and ch.get("available") and ch.get("files"):
        available.append("churn")
        for f in ch["files"]:
            ch_by_file[normalize_path(f["path"], repo_root)] = {
                "commits": f["commits"], "authors": f.get("authors"),
                "last_change": f.get("last_change"),
            }
    else:
        degradations.append(
            "Change frequency unavailable (no version control history, or history could "
            "not be read); its weight was redistributed. The risk ranking used two of its "
            "three inputs and this must be stated in the report.")

    # ---- coverage
    cv_by_file: dict[str, dict] = {}
    unmatched_coverage = []
    if cv and cv.get("files"):
        available.append("verification")
        known = set(cx_by_file) | set(ch_by_file)
        for f in cv["files"]:
            key = normalize_path(f["path"], repo_root)
            if known and key not in known:
                # The coverage run may have used a different working directory.
                matched = suffix_match(key, known)
                if matched:
                    key = matched
                else:
                    unmatched_coverage.append(f["path"])
            cv_by_file[key] = {
                "line_pct": f.get("line_pct"),
                "branch_pct": f.get("branch_pct"),
                "lines_total": f.get("lines_total"),
            }
    else:
        degradations.append(
            "No coverage data; every file is treated as unverified, which is correct when "
            "no suite exists but must not be presented as a measurement of zero coverage.")

    unverified = {normalize_path(p, repo_root) for p in args.unverified}

    # Redistribute the weights of any missing input across those present.
    active = {k: v for k, v in WEIGHTS.items()
              if k in available or k == "verification"}
    if not active:
        active = {"complexity": 1.0}
    total_w = sum(active.values())
    weights = {k: v / total_w for k, v in active.items()}

    paths = set(cx_by_file) | set(ch_by_file) | set(cv_by_file)
    if not paths:
        json.dump({"error": "no inputs produced any files to rank",
                   "degradations": degradations}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    max_cx = max((v["max_complexity"] for v in cx_by_file.values()), default=1) or 1
    max_ch = max((v["commits"] for v in ch_by_file.values()), default=1) or 1

    rows = []
    for p in sorted(paths):
        c = cx_by_file.get(p)
        k = ch_by_file.get(p)
        v = cv_by_file.get(p)

        cx_score = (c["max_complexity"] / max_cx) if c else 0.0
        ch_score = (k["commits"] / max_ch) if k else 0.0

        if p in unverified:
            ver_score = 0.0
            ver_note = "judged covered but not meaningfully verified"
        elif v and v.get("line_pct") is not None:
            ver_score = v["line_pct"] / 100.0
            ver_note = f"{v['line_pct']}% lines covered"
        else:
            ver_score = 0.0
            ver_note = "no coverage data" if not cv_by_file else "not present in coverage report"

        score = (weights.get("complexity", 0) * cx_score
                 + weights.get("verification", 0) * (1.0 - ver_score)
                 + weights.get("churn", 0) * ch_score)

        rows.append({
            "path": p,
            "risk_score": round(score, 4),
            "tier": None,  # assigned below, from position within this repository
            "complexity": {
                "max": c["max_complexity"] if c else None,
                "worst_function": c["worst_function"] if c else None,
                "basis": c["basis"] if c else "unavailable",
                "normalized": round(cx_score, 4),
            },
            "verification": {
                "line_pct": v.get("line_pct") if v else None,
                "note": ver_note,
                "normalized": round(ver_score, 4),
            },
            "churn": {
                "commits": k["commits"] if k else None,
                "last_change": k.get("last_change") if k else None,
                "normalized": round(ch_score, 4),
            },
        })

    rows.sort(key=lambda r: (-r["risk_score"], r["path"]))
    assign_tiers(rows)

    if unmatched_coverage:
        degradations.append(
            f"{len(unmatched_coverage)} file(s) in the coverage report could not be "
            "matched to any analyzed source file. Their coverage was not applied. This "
            "usually means the coverage run used a different working directory.")

    method = (
        "risk = "
        + " + ".join(f"{w:.2f} * {name}" for name, w in weights.items())
        + ". Complexity is the file's highest cyclomatic complexity normalized against "
          "the repository maximum. Verification is the covered-line fraction, inverted so "
          "unverified code scores higher, and forced to zero for files judged covered but "
          "not meaningfully verified. Churn is commit count normalized against the "
          "repository maximum. Tiers are assigned by rank position within this repository "
          "-- top tenth, next fifth, next third, remainder -- because absolute thresholds "
          "collapse when a repository has no tests at all or is uniformly well tested. "
          "All values are relative to this repository and are not comparable across "
          "repositories."
    )

    json.dump({
        "method": method,
        "weights_used": {k: round(v, 4) for k, v in weights.items()},
        "inputs_available": available,
        "inputs_missing": [k for k in WEIGHTS if k not in available],
        "files_ranked": len(rows),
        "tier_counts": {
            t: sum(1 for r in rows if r["tier"] == t)
            for t in ("top", "high", "medium", "low")
        },
        "degradations": degradations,
        "ranking": rows[:args.top],
        "all": rows,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

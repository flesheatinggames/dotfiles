#!/usr/bin/env python3
"""Parse coverage output into one shape, whatever tool produced it.

Handles the formats the supported ecosystems emit:

  coverage.py JSON   pytest --cov-report=json, or `coverage json`
  Cobertura XML      `coverage xml`, and many CI tools
  LCOV               Vitest, Jest, c8, nyc, Istanbul
  Istanbul JSON      Vitest and Jest `json` reporter
  Go profile         `go test -coverprofile` (trivial format, so it costs nothing)

The format is detected from the content, not the filename, because these tools disagree
about extensions.

Reports line coverage always, and branch coverage when the format carries it. When a
format has no branch data, the field is null rather than zero -- absent and zero are
different facts and the report must not confuse them.

Usage:
    python3 parse_coverage.py <file> --json
    python3 parse_coverage.py <file> --json --min-lines 0   # include fully-covered files
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# The coverage file comes from whatever repository is being assessed, so it is untrusted
# input. Prefer defusedxml when the environment happens to have it; otherwise fall back
# to the standard library and refuse any document carrying a document type or entity
# declaration. That refusal is what blocks entity-expansion and external-entity attacks,
# which are the only two things defusedxml would be protecting against here.
try:  # pragma: no cover - depends on the environment, not on our logic
    from defusedxml.ElementTree import parse as _xml_parse  # type: ignore
    _XML_HARDENED = True
except ImportError:
    from xml.etree.ElementTree import parse as _xml_parse
    _XML_HARDENED = False

_DOCTYPE_RE = re.compile(rb"<!(DOCTYPE|ENTITY)\b", re.IGNORECASE)


def safe_parse_xml(path: Path):
    """Parse XML, refusing documents that declare a doctype or entities."""
    if not _XML_HARDENED:
        with path.open("rb") as fh:
            head = fh.read(65536)
        if _DOCTYPE_RE.search(head):
            raise ValueError(
                "refusing to parse XML containing a DOCTYPE or ENTITY declaration; "
                "install defusedxml if this file is legitimate"
            )
    return _xml_parse(path)


def pct(covered: int, total: int) -> float | None:
    if not total:
        return None
    return round(100.0 * covered / total, 2)


def compress(numbers: list[int]) -> str:
    """Turn [1,2,3,7,9,10] into '1-3, 7, 9-10' for readable uncovered-line lists."""
    if not numbers:
        return ""
    nums = sorted(set(numbers))
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = n
    parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(parts)


# ------------------------------------------------------------------ format sniffing


def sniff(path: Path) -> str:
    head = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}")

    stripped = head.lstrip()
    if stripped.startswith("mode:"):
        return "go"
    if re.search(r"^(TN:|SF:)", head, re.MULTILINE):
        return "lcov"
    if stripped.startswith("<"):
        return "cobertura"
    if stripped.startswith("{"):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            return "unknown"
        if isinstance(data, dict):
            if "files" in data and "meta" in data:
                return "coveragepy"
            if data and all(isinstance(v, dict) and "statementMap" in v
                            for v in list(data.values())[:3]):
                return "istanbul"
        return "unknown"
    return "unknown"


# ---------------------------------------------------------------------- parsers


def parse_coveragepy(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    files = []
    for name, entry in (data.get("files") or {}).items():
        s = entry.get("summary", {}) or {}
        missing = entry.get("missing_lines", []) or []
        nb = s.get("num_branches")
        files.append({
            "path": name,
            "lines_total": s.get("num_statements", 0),
            "lines_covered": s.get("covered_lines", 0),
            "line_pct": pct(s.get("covered_lines", 0), s.get("num_statements", 0)),
            "branches_total": nb if nb else None,
            "branches_covered": s.get("covered_branches") if nb else None,
            "branch_pct": (pct(s.get("covered_branches", 0), nb) if nb else None),
            "uncovered_lines": compress(missing),
            "functions": [
                {"name": fname or "<module>",
                 "lines_total": (fs.get("summary", {}) or {}).get("num_statements", 0),
                 "lines_covered": (fs.get("summary", {}) or {}).get("covered_lines", 0),
                 "line_pct": pct((fs.get("summary", {}) or {}).get("covered_lines", 0),
                                 (fs.get("summary", {}) or {}).get("num_statements", 0))}
                for fname, fs in (entry.get("functions") or {}).items()
            ],
        })
    meta = data.get("meta", {}) or {}
    totals = data.get("totals", {}) or {}
    return {
        "format": "coverage.py JSON",
        "tool": f"coverage.py {meta.get('version', 'unknown version')}",
        "branch_coverage_available": bool(totals.get("num_branches")),
        "files": files,
    }


def parse_cobertura(path: Path) -> dict:
    root = safe_parse_xml(path).getroot()
    files = []
    for cls in root.iter("class"):
        name = cls.get("filename") or cls.get("name") or "?"
        lines = list(cls.iter("line"))
        total = len(lines)
        covered = sum(1 for ln in lines if int(ln.get("hits", "0") or 0) > 0)
        missing = [int(ln.get("number", 0)) for ln in lines
                   if int(ln.get("hits", "0") or 0) == 0]
        b_total = b_cov = 0
        for ln in lines:
            if ln.get("branch") == "true":
                m = re.search(r"(\d+)%\s*\((\d+)/(\d+)\)", ln.get("condition-coverage", ""))
                if m:
                    b_cov += int(m.group(2))
                    b_total += int(m.group(3))
        files.append({
            "path": name,
            "lines_total": total,
            "lines_covered": covered,
            "line_pct": pct(covered, total),
            "branches_total": b_total or None,
            "branches_covered": b_cov if b_total else None,
            "branch_pct": pct(b_cov, b_total) if b_total else None,
            "uncovered_lines": compress(missing),
            "functions": [],
        })
    return {
        "format": "Cobertura XML",
        "tool": f"cobertura-compatible (version attribute: {root.get('version', 'absent')})",
        "branch_coverage_available": any(f["branches_total"] for f in files),
        "files": files,
    }


def parse_lcov(path: Path) -> dict:
    files, cur = [], None
    text = path.read_text(encoding="utf-8", errors="replace")

    def flush():
        if cur is not None:
            cur["line_pct"] = pct(cur["lines_covered"], cur["lines_total"])
            cur["branch_pct"] = (pct(cur["branches_covered"], cur["branches_total"])
                                 if cur["branches_total"] else None)
            if not cur["branches_total"]:
                cur["branches_total"] = None
                cur["branches_covered"] = None
            cur["uncovered_lines"] = compress(cur.pop("_missing"))
            files.append(cur)

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            flush()
            cur = {"path": line[3:], "lines_total": 0, "lines_covered": 0,
                   "branches_total": 0, "branches_covered": 0, "_missing": [],
                   "functions": [], "_fn": {}}
        elif cur is None:
            continue
        elif line.startswith("DA:"):
            body = line[3:].split(",")
            if len(body) >= 2:
                num, hits = int(body[0]), int(body[1])
                cur["lines_total"] += 1
                if hits > 0:
                    cur["lines_covered"] += 1
                else:
                    cur["_missing"].append(num)
        elif line.startswith("BRDA:"):
            body = line[5:].split(",")
            if len(body) >= 4:
                cur["branches_total"] += 1
                if body[3] not in ("-", "0"):
                    cur["branches_covered"] += 1
        elif line.startswith("FN:"):
            body = line[3:].split(",", 1)
            if len(body) == 2:
                cur["_fn"][body[1]] = {"name": body[1], "line": int(body[0]), "hits": 0}
        elif line.startswith("FNDA:"):
            body = line[5:].split(",", 1)
            if len(body) == 2 and body[1] in cur["_fn"]:
                cur["_fn"][body[1]]["hits"] = int(body[0])
        elif line == "end_of_record":
            cur["functions"] = [
                {"name": f["name"], "line": f["line"], "covered": f["hits"] > 0}
                for f in cur.pop("_fn").values()
            ]
            flush()
            cur = None
    flush()

    for f in files:
        f.pop("_fn", None)
    return {
        "format": "LCOV",
        "tool": "lcov-compatible (Vitest, Jest, c8, nyc, or Istanbul)",
        "branch_coverage_available": any(f["branches_total"] for f in files),
        "files": files,
    }


def parse_istanbul(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    files = []
    for name, entry in data.items():
        stmts = entry.get("s", {}) or {}
        smap = entry.get("statementMap", {}) or {}
        total = len(stmts)
        covered = sum(1 for v in stmts.values() if v)
        missing = [smap[k]["start"]["line"] for k, v in stmts.items()
                   if not v and k in smap and "start" in smap[k]]
        branches = entry.get("b", {}) or {}
        b_total = sum(len(v) for v in branches.values())
        b_cov = sum(1 for v in branches.values() for hit in v if hit)
        fns = entry.get("f", {}) or {}
        fmap = entry.get("fnMap", {}) or {}
        files.append({
            "path": name,
            "lines_total": total,
            "lines_covered": covered,
            "line_pct": pct(covered, total),
            "branches_total": b_total or None,
            "branches_covered": b_cov if b_total else None,
            "branch_pct": pct(b_cov, b_total) if b_total else None,
            "uncovered_lines": compress(missing),
            "functions": [
                {"name": fmap.get(k, {}).get("name", k),
                 "line": (fmap.get(k, {}).get("decl", {}).get("start", {}) or {}).get("line"),
                 "covered": bool(v)}
                for k, v in fns.items()
            ],
        })
    return {
        "format": "Istanbul JSON",
        "tool": "Istanbul-compatible (Vitest or Jest json reporter)",
        "branch_coverage_available": any(f["branches_total"] for f in files),
        "files": files,
    }


def parse_go(path: Path) -> dict:
    per_file: dict[str, dict] = {}
    line_re = re.compile(r"^(?P<file>.+):(?P<sl>\d+)\.\d+,(?P<el>\d+)\.\d+ "
                         r"(?P<stmts>\d+) (?P<count>\d+)$")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        m = line_re.match(raw.strip())
        if not m:
            continue
        f = per_file.setdefault(m.group("file"),
                                {"lines_total": 0, "lines_covered": 0, "_missing": []})
        n = int(m.group("stmts"))
        f["lines_total"] += n
        if int(m.group("count")) > 0:
            f["lines_covered"] += n
        else:
            f["_missing"].extend(range(int(m.group("sl")), int(m.group("el")) + 1))
    files = [{
        "path": name,
        "lines_total": d["lines_total"],
        "lines_covered": d["lines_covered"],
        "line_pct": pct(d["lines_covered"], d["lines_total"]),
        "branches_total": None,
        "branches_covered": None,
        "branch_pct": None,
        "uncovered_lines": compress(d["_missing"]),
        "functions": [],
    } for name, d in per_file.items()]
    return {
        "format": "Go coverage profile",
        "tool": "go test -coverprofile",
        "branch_coverage_available": False,
        "files": files,
    }


PARSERS = {
    "coveragepy": parse_coveragepy,
    "cobertura": parse_cobertura,
    "lcov": parse_lcov,
    "istanbul": parse_istanbul,
    "go": parse_go,
}


# ------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="coverage output file")
    ap.add_argument("--min-lines", type=int, default=1,
                    help="omit files with fewer measurable lines than this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2

    fmt = sniff(path)
    if fmt == "unknown":
        json.dump({
            "source": str(path),
            "format": "unrecognized",
            "error": ("Could not recognize the coverage format. Supported: coverage.py "
                      "JSON, Cobertura XML, LCOV, Istanbul JSON, Go profile. Report this "
                      "as a degradation rather than reporting coverage numbers."),
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    try:
        result = PARSERS[fmt](path)
    except (ValueError, ET.ParseError, KeyError) as exc:
        json.dump({"source": str(path), "format": fmt,
                   "error": f"parse failed: {exc}"}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    files = [f for f in result["files"] if f["lines_total"] >= args.min_lines]
    files.sort(key=lambda f: (f["line_pct"] if f["line_pct"] is not None else 0,
                              -f["lines_total"]))

    lt = sum(f["lines_total"] for f in files)
    lc = sum(f["lines_covered"] for f in files)
    bt = sum(f["branches_total"] or 0 for f in files)
    bc = sum(f["branches_covered"] or 0 for f in files)

    result["source"] = str(path)
    result["files"] = files
    result["totals"] = {
        "files": len(files),
        "lines_total": lt,
        "lines_covered": lc,
        "line_pct": pct(lc, lt),
        "branches_total": bt or None,
        "branches_covered": bc if bt else None,
        "branch_pct": pct(bc, bt) if bt else None,
    }
    if not result["branch_coverage_available"]:
        result["note"] = ("This format or run carries no branch data. Branch coverage is "
                          "absent, which is not the same as zero, and the report must not "
                          "present it as a measurement.")

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the machine-readable index in a test-assessment report.

The index is a single fenced block whose info string is exactly ``json assessment-index``,
placed in the report's last numbered section. It carries stable identifiers for findings,
recommendations, exclusions, degradations, and open questions so that the planning stage
can reference them without depending on positional numbering.

This script checks three separate things:

1. The block exists, exactly once, and is valid JSON.
2. Every field conforms to ``references/index-schema.md``: required keys, types,
   identifier patterns, closed enumerations, and the acyclicity of the dependency graph.
3. Every identifier in the index appears in the report's prose, and every identifier-shaped
   token in the prose is defined in the index. Tiers stated in the prose findings table
   match the tiers in the index.

Check 3 is the one that matters most. An index that validates against the schema but
describes a report that does not exist is worse than no index at all, because a downstream
stage will trust it.

Usage:
    python3 check_index.py <report.md>
    python3 check_index.py <report.md> --json
"""

import argparse
import json
import re
import sys

INDEX_INFO_STRING = "json assessment-index"
SCHEMA_VERSION = "1.2"

# The three dispositions R-7.2 of the reporting document permits for an open run-ledger item.
# There is no fourth and in particular no "still investigating": an item nobody has looked at
# is `confirmed` with that as its evidence, which is a statement somebody has to write down.
RECONCILIATION_DISPOSITIONS = {"confirmed", "updated", "contested"}

ID_PATTERNS = {
    "findings": re.compile(r"^F[0-9]+$"),
    "recommendations": re.compile(r"^R[0-9]+$"),
    "exclusions": re.compile(r"^X[0-9]+$"),
    "degradations": re.compile(r"^D[0-9]+$"),
    "open_questions": re.compile(r"^Q[0-9]+$"),
}

# Matches any token that looks like an index identifier, used when scanning prose.
PROSE_ID = re.compile(r"(?<![A-Za-z0-9_-])([FRXDQ][0-9]+)(?![A-Za-z0-9_])")

# An absolute home-directory path inside a fenced block, which R-5.2 forbids because a
# command carrying one is reproducible by exactly one account on one machine.
#
# The core — /Users/ or /home/ — is the planning skill's rule for the same defect in a
# completion check's command (planlib.py, rule `absolute-path`), kept identical so the two
# stages agree on what an unreproducible path is. The left boundary is wider here: a
# report's block assigns paths to variables and quotes them, so `SKILL=/Users/...` and
# `"/home/..."` must both be caught, where a check's command field only ever had the path
# at a word boundary.
ABSOLUTE_HOME_PATH = re.compile(r"""(?:^|[\s=:"'`(\[])(/(?:Users|home)/[^\s"'`)\]]*)""")

TIERS = {"top", "high", "medium", "low"}
MODES = {"requirements-informed", "requirements-informed-partial", "inference"}
VERIFICATION = {"passed", "passed-with-corrections", "skipped"}
SIZES = {"small", "medium", "large"}
KINDS = {
    "seam",
    "test-infrastructure",
    "test-repair",
    "configuration",
    "deletion",
    "documentation",
    "other",
}
EXCLUSION_CATEGORIES = {"A", "B", "C", "D", "E", "F"}
UNIT_KINDS = {"functions", "statements", "lines", "files"}
DEP_TYPES = {"blocks", "partially-blocks", "precedes", "must-land-together"}
ORDERING_DEP_TYPES = {"blocks", "precedes"}
BASES = {"measured", "estimated"}

# The closed set of testability categories (R-6.7.3).
#
# `integration-only` is here and is not in the addendum's list of four. It is not an
# addition of convenience: the synthetic fixture already classifies two functions this way,
# and the seam catalog explicitly requires the report to say so when no catalog seam fits
# rather than invent a fifth seam type. Without the category those functions have nowhere
# legal to sit — `needs-seam` would demand a seam type the catalog refuses to supply, and
# `excluded` would claim Section 4 excluded code that Section 4 says nothing about — and
# the planning stage's enablement rule would hard-stop on them forever, asking for a
# classification that cannot be written.
TESTABILITY_CATEGORIES = {
    "testable-as-is",
    "export-only",
    "needs-seam",
    "integration-only",
    "excluded",
}

# Categories where something must happen before a unit test can reach the function, so the
# entry must name the recommendation that does it.
TESTABILITY_NEEDS_ENABLER = {"export-only", "needs-seam"}

MAP_GRANULARITIES = {
    "per-function",
    "public-interface",
    "module-summary",
    "one-line",
    "omitted",
}

# How a Section 8 table row's label maps to a category. Checked in order, first match wins,
# against the lowercased label with markdown emphasis stripped. Substring matching rather
# than equality is deliberate: one real report splits `needs-seam` across two rows that name
# the two different reasons ("Requires a seam — bound to import.meta.glob at build time"),
# and those rows must sum into one category rather than each failing to match.
TESTABILITY_ROW_PATTERNS = [
    ("excluded", ("excluded",)),
    ("integration-only", ("integration",)),
    ("export-only", ("export",)),
    ("needs-seam", ("seam",)),
    ("testable-as-is", ("testable",)),
]

# Rows that are totals rather than categories, and must not be counted as either.
TESTABILITY_TOTAL_LABELS = ("total", "meaningful total", "classified total", "sum")

# Percentage points of slack when comparing a stated share against the recomputed one.
# Reports round to whole percents or to one decimal; both land inside this.
SHARE_TOLERANCE = 0.75

TOP_LEVEL_KEYS = [
    "index_version",
    "repository",
    "report_path",
    "generated",
    "commit",
    "mode",
    "verification",
    "findings",
    "recommendations",
    "exclusions",
    "degradations",
    "open_questions",
    "dependencies",
    "coverage_baseline",
    "metrics",
    "testability",
    "testability_scope",
]


class Problems:
    """Collects failures with enough context to act on each one.

    Advisories are a second list, reported but not failing the report. Exactly one check
    uses them, and it earns the distinction: a superseded figure of `4` cannot be told apart
    from the word "4" in a sentence about something else, so failing on it would train
    whoever runs this to ignore the output. Reporting it and letting the reader judge is the
    honest handling of a check that cannot be certain.
    """

    def __init__(self):
        self.items = []
        self.advisories = []

    def add(self, rule, where, message, fix=None):
        self.items.append(
            {"rule": rule, "where": where, "message": message, "fix": fix}
        )

    def advise(self, rule, where, message, fix=None):
        self.advisories.append(
            {"rule": rule, "where": where, "message": message, "fix": fix}
        )

    def __len__(self):
        return len(self.items)


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------


def split_report(text):
    """Return (index_blocks, prose_lines, code_lines).

    ``index_blocks`` is a list of (start_line, json_text) for each block whose info string
    is exactly the index info string. ``prose_lines`` is the report with every fenced code
    block removed, as a list of (line_number, text), so identifier scanning never trips
    over an identifier that appears inside a code sample. ``code_lines`` is the complement:
    every line that sat inside a fence, in the same (line_number, text) form.

    The code lines are what the reproducibility check of R-5.2 reads. Prose may legitimately
    mention an absolute path while describing one; a command block may not contain one,
    because a command block exists to be run.

    Fence tracking handles nesting by length: the report template itself wraps its example
    in a four-backtick fence containing three-backtick fences. A closing fence must be at
    least as long as the fence that opened it, which is what the CommonMark rule says and
    is what makes the nested case work.
    """
    lines = text.splitlines()
    index_blocks = []
    prose = []
    code = []

    fence_char = None
    fence_len = 0
    fence_info = None
    fence_start = 0
    buffer = []
    numbered = []

    fence_re = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")

    for number, line in enumerate(lines, start=1):
        match = fence_re.match(line)
        if fence_char is None:
            if match and match.group(2)[0] in "`~":
                fence_char = match.group(2)[0]
                fence_len = len(match.group(2))
                fence_info = match.group(3).strip()
                fence_start = number
                buffer = []
                numbered = []
                continue
            prose.append((number, line))
            continue

        # Inside a fence: look for a closing fence of the same character, at least as long,
        # with nothing after it.
        if match and match.group(2)[0] == fence_char and len(match.group(2)) >= fence_len:
            if match.group(3).strip() == "":
                if fence_info == INDEX_INFO_STRING:
                    index_blocks.append((fence_start, "\n".join(buffer)))
                else:
                    code.extend(numbered)
                fence_char = None
                fence_info = None
                buffer = []
                numbered = []
                continue
        buffer.append(line)
        numbered.append((number, line))

    if fence_char is not None:
        if fence_info == INDEX_INFO_STRING:
            # Unterminated fence. Report it as such rather than silently accepting the body.
            index_blocks.append((fence_start, None))
        else:
            code.extend(numbered)

    return index_blocks, prose, code


def prose_identifiers(prose):
    """Every identifier-shaped token in the prose, mapped to the lines it appears on."""
    found = {}
    for number, line in prose:
        for token in PROSE_ID.findall(line):
            found.setdefault(token, []).append(number)
    return found


def parse_markdown_tables(prose):
    """Return every pipe table in the prose as (header_cells, rows, first_line_number).

    Rows are lists of cell strings with surrounding whitespace stripped. This is a
    deliberately small parser: it does not handle escaped pipes inside cells, and the
    caller must tolerate a cell that was split because it contained one. In practice the
    identifier and tier columns never contain pipes, and the report template escapes them
    (``\\|``) where they occur in quoted code.
    """
    tables = []
    current = None
    for number, line in prose:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if current is None:
                current = {"header": cells, "rows": [], "line": number, "seen_rule": False}
            elif not current["seen_rule"]:
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    current["seen_rule"] = True
                else:
                    # Two header-looking lines in a row: not a table we can read.
                    current = None
            else:
                current["rows"].append(cells)
        else:
            if current is not None and current["seen_rule"]:
                tables.append((current["header"], current["rows"], current["line"]))
            current = None
    if current is not None and current["seen_rule"]:
        tables.append((current["header"], current["rows"], current["line"]))
    return tables


# --------------------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------------------


def require(problems, condition, rule, where, message, fix=None):
    if not condition:
        problems.add(rule, where, message, fix)
    return condition


def check_string(problems, obj, key, where, allow_null=False, allow_empty=False):
    value = obj.get(key)
    if value is None and allow_null:
        return True
    if not isinstance(value, str):
        problems.add(
            "field-type",
            where,
            f"`{key}` must be a string{' or null' if allow_null else ''}, got "
            f"{type(value).__name__}",
        )
        return False
    if not allow_empty and not value.strip():
        problems.add("field-empty", where, f"`{key}` must not be empty")
        return False
    return True


def check_bool(problems, obj, key, where):
    if not isinstance(obj.get(key), bool):
        problems.add(
            "field-type",
            where,
            f"`{key}` must be true or false, got {type(obj.get(key)).__name__}",
        )
        return False
    return True


def check_list(problems, obj, key, where, of=str):
    value = obj.get(key)
    if not isinstance(value, list):
        problems.add(
            "field-type",
            where,
            f"`{key}` must be a list (write `[]` for none, never omit it), got "
            f"{type(value).__name__}",
        )
        return False
    for i, item in enumerate(value):
        if not isinstance(item, of):
            problems.add(
                "field-type",
                where,
                f"`{key}[{i}]` must be {of.__name__}, got {type(item).__name__}",
            )
            return False
    return True


def check_contested(problems, obj, where):
    contested = obj.get("contested", "missing")
    if contested == "missing":
        problems.add(
            "field-missing",
            where,
            "`contested` is required. Write `null` when the claim is settled",
        )
        return
    if contested is None:
        return
    if not isinstance(contested, dict):
        problems.add("field-type", where, "`contested` must be an object or null")
        return
    readings = contested.get("readings")
    if not isinstance(readings, list) or len(readings) < 2:
        problems.add(
            "contested-readings",
            where,
            "a contested item needs at least two readings; one reading is not a contest",
        )
    check_string(problems, contested, "settled_by", where)


def validate_schema(index, problems):
    where = "index"

    for key in TOP_LEVEL_KEYS:
        if key not in index:
            problems.add(
                "field-missing",
                where,
                f"required top-level key `{key}` is absent",
                "See references/index-schema.md. Empty lists are written `[]`, never omitted.",
            )

    version = index.get("index_version")
    if version != SCHEMA_VERSION:
        fix = None
        if version == "1.0":
            fix = (
                "1.0 is this schema without `testability` and `testability_scope`. Add "
                "those two sections per Step 6 of the procedure, then follow the 1.1 "
                f"instruction below, and set the version to {SCHEMA_VERSION}. Nothing else "
                "needs re-measuring."
            )
        elif version == "1.1":
            # A 1.1 index is not malformed; it predates the run ledger. The remedy is a
            # bounded backfill rather than a re-assessment, and saying which of the two is
            # needed is the whole point of routing a version rather than refusing it.
            fix = (
                "1.1 is this schema before the run ledger existed. If the repository has no "
                f"docs/test-ledger.json, set the version to {SCHEMA_VERSION} and change "
                "nothing else. If it has one, add a `reconciliation` array with one entry per "
                "open ledger item — `confirmed`, `updated`, or `contested`, each with its "
                "evidence — and the matching prose section 13. Nothing is re-measured either "
                "way."
            )
        problems.add(
            "version",
            where,
            f"`index_version` must be \"{SCHEMA_VERSION}\", got {version!r}",
            fix,
        )

    for key in ("repository", "report_path", "generated"):
        check_string(problems, index, key, where)
    check_string(problems, index, "commit", where, allow_null=True)

    if index.get("mode") not in MODES:
        problems.add(
            "enum",
            where,
            f"`mode` must be one of {sorted(MODES)}, got {index.get('mode')!r}",
        )
    if index.get("verification") not in VERIFICATION:
        problems.add(
            "enum",
            where,
            f"`verification` must be one of {sorted(VERIFICATION)}, got "
            f"{index.get('verification')!r}",
        )

    ids = validate_nodes(index, problems)
    validate_dependencies(index, problems, ids)
    validate_independence(index, problems)
    validate_coverage_baseline(index, problems)
    validate_metrics(index, problems)
    validate_testability(index, problems)
    validate_testability_scope(index, problems)
    validate_reconciliation(index, problems)
    return ids


def validate_reconciliation(index, problems):
    """The `reconciliation` array's shape, when the index carries one.

    Optional at 1.2 and required by `--ledger`. A repository with no run ledger has nothing to
    reconcile, and demanding an empty array from every such report would be ceremony. What is
    checked here is only that an array which exists is well formed; whether it is *complete* is
    a question about the ledger, and it is asked by `--ledger` because only then is there
    something to be complete against.
    """
    entries = index.get("reconciliation")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.add(
            "field-type", "index", "`reconciliation` must be a list of objects"
        )
        return
    seen = set()
    for position, entry in enumerate(entries):
        where = f"index.reconciliation[{position}]"
        if not isinstance(entry, dict):
            problems.add("field-type", where, "each reconciliation entry is an object")
            continue
        item = entry.get("item")
        check_string(problems, entry, "item", where)
        if isinstance(item, str):
            if item in seen:
                problems.add(
                    "duplicate-id",
                    where,
                    f"{item} is reconciled twice, so the report says two things about one item",
                )
            seen.add(item)
        disposition = entry.get("disposition")
        if disposition not in RECONCILIATION_DISPOSITIONS:
            problems.add(
                "enum",
                where,
                f"`disposition` must be one of {sorted(RECONCILIATION_DISPOSITIONS)}, got "
                f"{disposition!r}",
                "R-7.2 of the reporting document permits exactly three. There is no "
                "`investigating`: an item nobody has looked at is `confirmed`, and writing "
                "that down is the point.",
            )
        check_string(problems, entry, "evidence", where)
        if isinstance(entry.get("evidence"), str) and len(entry["evidence"].strip()) < 20:
            problems.add(
                "field-too-short",
                where,
                f"the evidence for {item} is {len(entry['evidence'].strip())} characters",
                "All three dispositions carry evidence, and `confirmed` needs it most rather "
                "than least: it is the one that costs nothing to write and asserts the most, "
                "that somebody looked and the item is still true. An unevidenced `confirmed` "
                "is indistinguishable from not having looked.",
            )


def validate_independence(index, problems):
    """`independent` must agree with the dependency edges.

    Independence is scoped to the other recommendations, which is how the reports use the
    word ("R3 is independent of all of the above"). An edge to a finding or to an open
    question does not make a recommendation dependent on another recommendation, and the
    planner benefits from being able to tell those two situations apart.
    """
    recommendations = index.get("recommendations")
    if not isinstance(recommendations, list):
        return
    rec_ids = {
        r["id"]
        for r in recommendations
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }

    connected = {}
    for edge in index.get("dependencies") or []:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("from"), edge.get("to")
        if source in rec_ids and target in rec_ids:
            connected.setdefault(source, []).append(target)
            connected.setdefault(target, []).append(source)

    for i, rec in enumerate(recommendations):
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            continue
        node_id = rec["id"]
        where = f"recommendations[{i}] ({node_id})"
        others = connected.get(node_id, [])
        if rec.get("independent") is True and others:
            problems.add(
                "independence",
                where,
                f"{node_id} is marked independent but a dependency edge connects it to "
                + ", ".join(sorted(set(others))),
                "Independence means no edge to another recommendation. Edges to findings and "
                "open questions do not count; edges to recommendations do.",
            )
        if rec.get("independent") is False and not others:
            problems.add(
                "independence",
                where,
                f"{node_id} is marked not independent, but no dependency edge connects it to "
                "another recommendation",
                "Either add the edge the prose states, or set `independent` to true.",
            )


def validate_nodes(index, problems):
    """Validate every node list. Returns the set of every identifier defined."""
    ids = set()

    def claim_id(section, obj, position):
        where = f"{section}[{position}]"
        node_id = obj.get("id")
        if not isinstance(node_id, str) or not ID_PATTERNS[section].match(node_id):
            problems.add(
                "id-format",
                where,
                f"`id` must match {ID_PATTERNS[section].pattern}, got {node_id!r}",
            )
            return None
        if node_id in ids:
            problems.add("id-duplicate", where, f"identifier {node_id} is used twice")
            return None
        ids.add(node_id)
        return node_id

    # ---- findings -----------------------------------------------------------------
    findings = index.get("findings")
    if isinstance(findings, list):
        ranks = {}
        for i, finding in enumerate(findings):
            if not isinstance(finding, dict):
                problems.add("field-type", f"findings[{i}]", "each finding must be an object")
                continue
            node_id = claim_id("findings", finding, i)
            where = f"findings[{i}] ({node_id or '?'})"
            check_string(problems, finding, "title", where)
            check_string(problems, finding, "basis", where)
            check_list(problems, finding, "files", where)
            check_contested(problems, finding, where)
            if finding.get("tier") not in TIERS:
                problems.add(
                    "enum",
                    where,
                    f"`tier` must be one of {sorted(TIERS)}, got {finding.get('tier')!r}",
                )
            rank = finding.get("rank")
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                problems.add("field-type", where, "`rank` must be an integer of at least 1")
            elif rank in ranks:
                problems.add(
                    "rank-duplicate",
                    where,
                    f"rank {rank} is also used by {ranks[rank]}; ranks are distinct",
                )
            else:
                ranks[rank] = node_id

    # ---- recommendations ----------------------------------------------------------
    recommendations = index.get("recommendations")
    if isinstance(recommendations, list):
        for i, rec in enumerate(recommendations):
            if not isinstance(rec, dict):
                problems.add(
                    "field-type", f"recommendations[{i}]", "each recommendation must be an object"
                )
                continue
            node_id = claim_id("recommendations", rec, i)
            where = f"recommendations[{i}] ({node_id or '?'})"
            check_string(problems, rec, "title", where)
            check_list(problems, rec, "locations", where)
            check_list(problems, rec, "addresses", where)
            check_bool(problems, rec, "characterization_required", where)
            check_bool(problems, rec, "safe_to_execute", where)
            check_bool(problems, rec, "independent", where)
            check_contested(problems, rec, where)

            kind = rec.get("kind")
            if kind not in KINDS:
                problems.add(
                    "enum", where, f"`kind` must be one of {sorted(KINDS)}, got {kind!r}"
                )
            if kind == "other":
                check_string(problems, rec, "kind_note", where)

            seam_type = rec.get("seam_type", "missing")
            if seam_type == "missing":
                problems.add("field-missing", where, "`seam_type` is required (write null for a non-seam)")
            elif kind == "seam":
                if seam_type not in (1, 2, 3, 4):
                    problems.add(
                        "seam-type",
                        where,
                        "a `seam` recommendation must name a catalog seam type 1-4, got "
                        f"{seam_type!r}",
                        "The seam catalog is closed. If no catalog seam fits, the kind is not `seam`.",
                    )
            elif seam_type is not None:
                problems.add(
                    "seam-type",
                    where,
                    f"`seam_type` must be null when kind is {kind!r}, got {seam_type!r}",
                )

            if rec.get("size") not in SIZES:
                problems.add(
                    "enum", where, f"`size` must be one of {sorted(SIZES)}, got {rec.get('size')!r}"
                )

            if isinstance(rec.get("locations"), list) and not rec.get("locations"):
                problems.add("locations-empty", where, "a recommendation needs at least one location")

            required_char = rec.get("characterization_required")
            for key in ("characterization_boundary", "characterization_note"):
                if key not in rec:
                    problems.add("field-missing", where, f"`{key}` is required (write null when not applicable)")
                elif required_char is True:
                    check_string(problems, rec, key, where)
                elif required_char is False and rec.get(key) is not None:
                    # Permitted: the report often explains *why* no characterization is needed.
                    check_string(problems, rec, key, where, allow_null=True)

    # ---- exclusions ---------------------------------------------------------------
    exclusions = index.get("exclusions")
    if isinstance(exclusions, list):
        for i, exclusion in enumerate(exclusions):
            if not isinstance(exclusion, dict):
                problems.add("field-type", f"exclusions[{i}]", "each exclusion must be an object")
                continue
            node_id = claim_id("exclusions", exclusion, i)
            where = f"exclusions[{i}] ({node_id or '?'})"
            if check_list(problems, exclusion, "paths", where) and not exclusion["paths"]:
                problems.add("paths-empty", where, "an exclusion must name at least one path")
            check_string(problems, exclusion, "reason", where)
            check_bool(problems, exclusion, "belongs_in_tool_config", where)
            check_string(problems, exclusion, "verification_limit", where, allow_null=True)
            check_contested(problems, exclusion, where)

            category = exclusion.get("category", "missing")
            if category == "missing":
                problems.add("field-missing", where, "`category` is required (write null when the catalog has no matching category)")
            elif category is not None and category not in EXCLUSION_CATEGORIES:
                problems.add(
                    "enum",
                    where,
                    f"`category` must be one of {sorted(EXCLUSION_CATEGORIES)} or null, got {category!r}",
                )

            units = exclusion.get("units", "missing")
            unit_kind = exclusion.get("unit_kind", "missing")
            if units == "missing" or unit_kind == "missing":
                problems.add("field-missing", where, "`units` and `unit_kind` are both required (write null for each when the report gives no count)")
            elif units is None:
                if unit_kind is not None:
                    problems.add("units", where, "`unit_kind` must be null when `units` is null")
            else:
                if not isinstance(units, int) or isinstance(units, bool) or units < 0:
                    problems.add("field-type", where, "`units` must be a non-negative integer or null")
                if unit_kind not in UNIT_KINDS:
                    problems.add(
                        "enum",
                        where,
                        f"`unit_kind` must be one of {sorted(UNIT_KINDS)}, got {unit_kind!r}",
                    )

    # ---- degradations -------------------------------------------------------------
    degradations = index.get("degradations")
    if isinstance(degradations, list):
        for i, degradation in enumerate(degradations):
            if not isinstance(degradation, dict):
                problems.add("field-type", f"degradations[{i}]", "each degradation must be an object")
                continue
            node_id = claim_id("degradations", degradation, i)
            where = f"degradations[{i}] ({node_id or '?'})"
            check_string(problems, degradation, "degradation", where)
            check_string(problems, degradation, "effect", where)

    # ---- open questions -----------------------------------------------------------
    questions = index.get("open_questions")
    if isinstance(questions, list):
        for i, question in enumerate(questions):
            if not isinstance(question, dict):
                problems.add("field-type", f"open_questions[{i}]", "each open question must be an object")
                continue
            node_id = claim_id("open_questions", question, i)
            where = f"open_questions[{i}] ({node_id or '?'})"
            check_string(problems, question, "question", where)
            check_string(problems, question, "why_unanswered", where)
            if check_list(problems, question, "raised_by", where) and not question["raised_by"]:
                problems.add(
                    "raised-by-empty",
                    where,
                    "an open question must name at least one finding or recommendation that raises it",
                )

    return ids


def validate_dependencies(index, problems, ids):
    dependencies = index.get("dependencies")
    if not isinstance(dependencies, list):
        return
    edges = []
    for i, edge in enumerate(dependencies):
        where = f"dependencies[{i}]"
        if not isinstance(edge, dict):
            problems.add("field-type", where, "each dependency must be an object")
            continue
        check_string(problems, edge, "note", where)
        source, target = edge.get("from"), edge.get("to")
        edge_type = edge.get("type")
        if edge_type not in DEP_TYPES:
            problems.add(
                "enum", where, f"`type` must be one of {sorted(DEP_TYPES)}, got {edge_type!r}"
            )
        for role, value in (("from", source), ("to", target)):
            if not isinstance(value, str):
                problems.add("field-type", where, f"`{role}` must be a string identifier")
            elif value not in ids:
                problems.add(
                    "dangling-edge",
                    where,
                    f"`{role}` names {value!r}, which is not defined anywhere in this index",
                    "Every dependency endpoint must be an identifier. Free-text endpoints "
                    "such as \"the threshold decision\" become open questions with Q-numbers.",
                )
        if isinstance(source, str) and source == target:
            problems.add("self-edge", where, f"{source} depends on itself")
        if edge_type in ORDERING_DEP_TYPES and isinstance(source, str) and isinstance(target, str):
            edges.append((source, target))

    cycle = find_cycle(edges)
    if cycle:
        problems.add(
            "cycle",
            "dependencies",
            "the ordering edges (`blocks` and `precedes`) form a cycle: "
            + " -> ".join(cycle),
            "One of these edges is wrong, or one of them is really `must-land-together`.",
        )


def find_cycle(edges):
    graph = {}
    for source, target in edges:
        graph.setdefault(source, []).append(target)
        graph.setdefault(target, [])

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    stack = []

    def visit(node):
        colour[node] = GREY
        stack.append(node)
        for neighbour in graph[node]:
            if colour[neighbour] == GREY:
                return stack[stack.index(neighbour):] + [neighbour]
            if colour[neighbour] == WHITE:
                found = visit(neighbour)
                if found:
                    return found
        stack.pop()
        colour[node] = BLACK
        return None

    for node in sorted(graph):
        if colour[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def validate_coverage_baseline(index, problems):
    baseline = index.get("coverage_baseline")
    where = "coverage_baseline"
    if not isinstance(baseline, dict):
        problems.add("field-type", where, "`coverage_baseline` must be an object")
        return
    if not check_bool(problems, baseline, "available", where):
        return

    if baseline["available"]:
        for key in ("tool", "command", "config_in_effect", "scope_caveat"):
            if key not in baseline:
                problems.add("field-missing", where, f"`{key}` is required (write null if unknown)")
            else:
                check_string(problems, baseline, key, where, allow_null=True)
        overall = baseline.get("overall")
        if overall is None:
            problems.add(
                "baseline",
                where,
                "`available` is true but `overall` is null; a baseline with no overall figure "
                "is not a baseline",
            )
        elif not isinstance(overall, dict):
            problems.add("field-type", where, "`overall` must be an object or null")
        else:
            for metric, value in overall.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    problems.add(
                        "field-type",
                        where,
                        f"`overall.{metric}` must be a number, got {type(value).__name__}",
                    )
        if not check_bool(problems, baseline, "files_complete", where):
            pass
        files = baseline.get("files")
        if not isinstance(files, list):
            problems.add("field-type", where, "`files` must be a list (write `[]` for none)")
        else:
            for i, entry in enumerate(files):
                sub = f"{where}.files[{i}]"
                if not isinstance(entry, dict):
                    problems.add("field-type", sub, "each entry must be an object")
                    continue
                check_string(problems, entry, "path", sub)
                for metric in ("lines", "branches", "functions"):
                    if metric in entry and entry[metric] is not None:
                        if not isinstance(entry[metric], (int, float)) or isinstance(
                            entry[metric], bool
                        ):
                            problems.add("field-type", sub, f"`{metric}` must be a number or null")
    else:
        check_string(problems, baseline, "reason", where)
        denominator = baseline.get("intended_denominator", "missing")
        if denominator == "missing":
            problems.add(
                "field-missing",
                where,
                "`intended_denominator` is required when no baseline exists (write null only "
                "when the report states none)",
            )
        elif isinstance(denominator, dict):
            if denominator.get("unit") not in UNIT_KINDS:
                problems.add(
                    "enum",
                    where,
                    f"`intended_denominator.unit` must be one of {sorted(UNIT_KINDS)}",
                )
            if not isinstance(denominator.get("count"), int) or isinstance(
                denominator.get("count"), bool
            ):
                problems.add("field-type", where, "`intended_denominator.count` must be an integer")


def validate_metrics(index, problems):
    metrics = index.get("metrics")
    if not isinstance(metrics, list):
        problems.add("field-type", "metrics", "`metrics` must be a list")
        return
    seen = set()
    for i, metric in enumerate(metrics):
        where = f"metrics[{i}]"
        if not isinstance(metric, dict):
            problems.add("field-type", where, "each metric must be an object")
            continue
        if check_string(problems, metric, "name", where):
            name = metric["name"]
            if not re.fullmatch(r"[a-z0-9_]+", name):
                problems.add(
                    "metric-name",
                    where,
                    f"`name` must be lowercase with underscores, got {name!r}",
                )
            if name in seen:
                problems.add("metric-duplicate", where, f"metric {name!r} appears twice")
            seen.add(name)
        value = metric.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.add("field-type", where, "`value` must be a number")
        if metric.get("basis") not in BASES:
            problems.add(
                "enum",
                where,
                f"`basis` must be `measured` or `estimated`, got {metric.get('basis')!r}",
                "Step 7b of the procedure already made this call. Copy it; do not re-decide it.",
            )
        check_string(problems, metric, "note", where)

        superseded = metric.get("superseded")
        if superseded is None:
            continue
        if not isinstance(superseded, list):
            problems.add(
                "field-type",
                where,
                "`superseded` must be a list of the values this figure previously held",
            )
            continue
        for position, old in enumerate(superseded):
            if not isinstance(old, (int, float)) or isinstance(old, bool):
                problems.add(
                    "field-type",
                    where,
                    f"`superseded[{position}]` must be a number, got {old!r}",
                )
            elif old == value:
                problems.add(
                    "metric-superseded-current",
                    where,
                    f"`superseded` contains {old!r}, which is this figure's current value",
                    "A value cannot supersede itself. figures.py drops these; a hand-edited "
                    "index can reintroduce one, and it would make the prose check fail on "
                    "the correct number.",
                )


# --------------------------------------------------------------------------------------
# Function-granularity testability (R-6.7.3)
# --------------------------------------------------------------------------------------


def path_matches(path, pattern):
    """Whether a repository-relative path falls under an exclusion's path or glob.

    Handles the three shapes exclusions actually use: an exact file path, a directory
    prefix written with a trailing ``**``, and an ordinary glob. Written out rather than
    delegated to ``fnmatch`` alone because ``fnmatch`` treats ``*`` as matching separators,
    which would make ``src/*`` swallow the whole tree.
    """
    if path == pattern:
        return True
    trimmed = pattern.rstrip("*").rstrip("/")
    if pattern.endswith("**") and (path == trimmed or path.startswith(trimmed + "/")):
        return True
    # Ordinary glob: `*` and `?` stop at a separator, `**` crosses them.
    regex = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**", i):
            regex.append(".*")
            i += 2
        elif char == "*":
            regex.append("[^/]*")
            i += 1
        elif char == "?":
            regex.append("[^/]")
            i += 1
        else:
            regex.append(re.escape(char))
            i += 1
    return re.fullmatch("".join(regex), path) is not None


def validate_testability(index, problems):
    """Validate the per-function testability entries.

    This section is the planning stage's claim-enablement input. A claim's `path:line`
    location resolves against `line`/`end_line` here, so a malformed range does not fail
    loudly — it silently stops resolving, and the planner then hard-stops asking for a
    backfill of a function that is already classified. That is why the range checks are as
    strict as the enumeration checks.
    """
    entries = index.get("testability")
    if not isinstance(entries, list):
        problems.add(
            "field-type",
            "testability",
            "`testability` must be a list, written `[]` when nothing was classified",
            "See references/index-schema.md. This is the input stage two's claim-enablement "
            "rule consumes; it cannot run without it.",
        )
        return

    recommendation_ids = {
        r["id"]
        for r in index.get("recommendations") or []
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }
    exclusion_paths = [
        (x.get("id"), p)
        for x in index.get("exclusions") or []
        if isinstance(x, dict)
        for p in (x.get("paths") or [])
        if isinstance(p, str)
    ]

    seen = {}
    for i, entry in enumerate(entries):
        where = f"testability[{i}]"
        if not isinstance(entry, dict):
            problems.add("field-type", where, "each testability entry must be an object")
            continue

        ok_file = check_string(problems, entry, "file", where)
        ok_function = check_string(problems, entry, "function", where)
        if ok_file and ok_function:
            where = f"testability[{i}] ({entry['file']}:{entry['function']})"

        line = entry.get("line")
        end_line = entry.get("end_line")
        for key, value in (("line", line), ("end_line", end_line)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                problems.add(
                    "field-type",
                    where,
                    f"`{key}` must be a positive integer, got {value!r}",
                    "complexity.py emits `line` and `end_line` for every function. Copy "
                    "them; a hand-written range that is off by two stops resolving.",
                )
        if (
            isinstance(line, int)
            and isinstance(end_line, int)
            and not isinstance(line, bool)
            and not isinstance(end_line, bool)
            and end_line < line
        ):
            problems.add(
                "testability-range",
                where,
                f"`end_line` ({end_line}) is before `line` ({line}), so no location can "
                "resolve to this entry",
            )

        category = entry.get("category")
        if category not in TESTABILITY_CATEGORIES:
            problems.add(
                "enum",
                where,
                f"`category` must be one of {sorted(TESTABILITY_CATEGORIES)}, got "
                f"{category!r}",
            )

        seam_type = entry.get("seam_type", "missing")
        if seam_type == "missing":
            problems.add(
                "field-missing",
                where,
                "`seam_type` is required. Write `null` where the category is not `needs-seam`",
            )
        elif category == "needs-seam":
            if seam_type not in (1, 2, 3, 4) or isinstance(seam_type, bool):
                problems.add(
                    "testability-seam-type",
                    where,
                    f"`needs-seam` requires a catalog seam type of 1 to 4, got {seam_type!r}",
                    "The seam catalog is closed. If no catalog seam fits, the category is "
                    "`integration-only`, not a fifth seam type.",
                )
        elif seam_type is not None:
            problems.add(
                "testability-seam-type",
                where,
                f"`seam_type` must be null when the category is {category!r}, got "
                f"{seam_type!r}",
            )

        seam_ref = entry.get("seam_ref", "missing")
        if seam_ref == "missing":
            problems.add(
                "field-missing",
                where,
                "`seam_ref` is required. Write `null` where nothing has to happen first",
            )
        elif category in TESTABILITY_NEEDS_ENABLER:
            if not isinstance(seam_ref, str) or not seam_ref:
                problems.add(
                    "testability-seam-ref",
                    where,
                    f"category {category!r} means a test cannot reach this function until "
                    "some recommendation runs, so `seam_ref` must name that recommendation",
                    "Without it the planner cannot tell which work item enables the claim, "
                    "and the enablement rule has nothing to check the dependency against.",
                )
            elif seam_ref not in recommendation_ids:
                problems.add(
                    "testability-seam-ref",
                    where,
                    f"`seam_ref` is {seam_ref!r}, which this index does not define as a "
                    "recommendation",
                )
        elif seam_ref is not None:
            problems.add(
                "testability-seam-ref",
                where,
                f"`seam_ref` must be null when the category is {category!r}, got "
                f"{seam_ref!r}",
            )

        check_string(problems, entry, "note", where, allow_null=True)

        if category == "excluded" and isinstance(entry.get("file"), str):
            if not any(path_matches(entry["file"], p) for _, p in exclusion_paths):
                problems.add(
                    "testability-not-excluded",
                    where,
                    f"this entry is categorised `excluded`, but {entry['file']} falls under "
                    "no exclusion's paths",
                    "An exclusion made in the index and nowhere else is exactly what the "
                    "prose cross-check exists to prevent. Either add the exclusion to "
                    "Section 4 with its reason, or classify the function honestly.",
                )

        if ok_file and ok_function and isinstance(line, int):
            key = (entry["file"], entry["function"], line)
            if key in seen:
                problems.add(
                    "testability-duplicate",
                    where,
                    f"{entry['file']}:{entry['function']} at line {line} is already "
                    f"classified at testability[{seen[key]}]",
                    "A location that resolves to two entries has no single category.",
                )
            else:
                seen[key] = i

    # Two entries starting on the same line is normal and harmless: a chained
    # `xs.filter(...).map(...)` is two callbacks on one line, and a parser that reports every
    # function reports both. What matters is whether a claim located there would resolve to
    # two *different* categories, because then the planner's answer depends on which entry it
    # happened to pick. Same category, same answer, no problem — so the check is on the
    # categories rather than on the collision.
    by_start = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        key = (entry.get("file"), entry.get("line"))
        if key[0] is None or not isinstance(key[1], int):
            continue
        by_start.setdefault(key, []).append((entry.get("function"), entry.get("category")))
    for (file, line), members in sorted(by_start.items(), key=lambda kv: str(kv[0])):
        categories = {category for _, category in members}
        if len(categories) > 1:
            problems.add(
                "testability-ambiguous",
                f"testability ({file}:{line})",
                f"{len(members)} entries start at {file}:{line} and disagree about the "
                "category: "
                + ", ".join(f"{name} is {category}" for name, category in members),
                "A claim located here would resolve to whichever entry the planner picked. "
                "Give the enclosing function the category that governs, or locate claims on "
                "a line only one of them covers.",
            )


def validate_testability_scope(index, problems):
    """Validate the object that bounds the list above.

    The scope is not bookkeeping. `complete` is what lets the planner distinguish a claim
    against something that is not a function — a planning error — from a claim against a
    function outside the classified set, whose remedy is a narrow backfill. Getting the flag
    wrong turns one of those into the other.
    """
    where = "testability_scope"
    scope = index.get("testability_scope")
    if not isinstance(scope, dict):
        problems.add(
            "field-type",
            where,
            "`testability_scope` must be an object recording what bounds the testability list",
        )
        return

    tiers = scope.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        problems.add(
            "field-type",
            where,
            "`tiers` must be a non-empty list of the risk tiers classified exhaustively",
        )
    else:
        for tier in tiers:
            if tier not in TIERS:
                problems.add(
                    "enum", where, f"`tiers` contains {tier!r}, which is not a risk tier"
                )

    recommendation_ids = {
        r["id"]
        for r in index.get("recommendations") or []
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }
    pulled_in = scope.get("recommendation_locations")
    if not isinstance(pulled_in, list):
        problems.add(
            "field-type",
            where,
            "`recommendation_locations` must be a list, written `[]` when no recommendation "
            "locations were pulled in",
        )
    else:
        for node_id in pulled_in:
            if node_id not in recommendation_ids:
                problems.add(
                    "testability-scope-ref",
                    where,
                    f"`recommendation_locations` names {node_id!r}, which this index does "
                    "not define as a recommendation",
                )

    granularity = scope.get("map_granularity")
    if not isinstance(granularity, dict):
        problems.add(
            "field-type",
            where,
            "`map_granularity` must be an object mapping each risk tier to the granularity "
            "the behavioral map used for it",
        )
    else:
        for tier, value in sorted(granularity.items()):
            if tier not in TIERS:
                problems.add(
                    "enum",
                    where,
                    f"`map_granularity` has a key {tier!r}, which is not a risk tier",
                )
            if value not in MAP_GRANULARITIES:
                problems.add(
                    "enum",
                    where,
                    f"`map_granularity[{tier!r}]` is {value!r}; must be one of "
                    f"{sorted(MAP_GRANULARITIES)}",
                )

    check_bool(problems, scope, "complete", where)

    entries = index.get("testability")
    classified = scope.get("classified_functions")
    if not isinstance(classified, int) or isinstance(classified, bool) or classified < 0:
        problems.add(
            "field-type", where, "`classified_functions` must be a non-negative integer"
        )
    elif isinstance(entries, list) and classified != len(entries):
        problems.add(
            "testability-scope-count",
            where,
            f"`classified_functions` is {classified} but `testability` has {len(entries)} "
            "entries",
            "The two must agree, because the prose cross-check compares the prose's counts "
            "against the entries and this number is what the prose is expected to state.",
        )

    total = scope.get("total_functions", "missing")
    if total == "missing":
        problems.add(
            "field-missing",
            where,
            "`total_functions` is required. Write `null` where no function count exists",
        )
    elif total is not None and (not isinstance(total, int) or isinstance(total, bool)):
        problems.add("field-type", where, "`total_functions` must be an integer or null")
    elif isinstance(total, int) and isinstance(classified, int) and classified > total:
        problems.add(
            "testability-scope-count",
            where,
            f"`classified_functions` ({classified}) exceeds `total_functions` ({total})",
        )

    if scope.get("complete") is True and isinstance(total, int) and isinstance(classified, int):
        if classified != total:
            problems.add(
                "testability-scope-complete",
                where,
                f"`complete` is true, but {classified} of {total} functions are classified",
                "`complete` means the classified set is every function in the repository. "
                "With a bounded set it must be false, so the planner backfills rather than "
                "concluding the function does not exist.",
            )

    check_string(problems, scope, "note", where)


# --------------------------------------------------------------------------------------
# Reproducibility of the report's commands (R-5.2)
# --------------------------------------------------------------------------------------


def check_reproducible_paths(code, problems):
    """No fenced block may carry an absolute home-directory path.

    Section 12 of the report exists so that a later stage, another person, or the same
    person in a different checkout can re-run the measurement and compare. A block
    containing `/Users/someone/Projects/...` reproduces it for one account on one machine,
    which is the same as not recording it. One of the two validation reports embedded such
    paths while the other used the variable form, so the practice was inconsistent within a
    single build and needed a check rather than a convention.

    The check reads code blocks only. Prose may legitimately quote an absolute path while
    describing one — "the report embedded /Users/..." is a true sentence about a defect, not
    the defect.
    """
    for number, line in code:
        for match in ABSOLUTE_HOME_PATH.finditer(line):
            problems.add(
                "absolute-path",
                f"prose:line {number}",
                f"a fenced block contains the absolute path `{match.group(1)}`, so nobody "
                "else and no other checkout can run it",
                "Write the skill's location as a variable defined once at the top of the "
                "block (`SKILL=<path to the test-assessment skill>/scripts`) and the "
                "repository as `.`. See references/report-template.md, Section 12.",
            )


# --------------------------------------------------------------------------------------
# Cross-check against the prose
# --------------------------------------------------------------------------------------


def cross_check_prose(index, prose, ids, problems):
    in_prose = prose_identifiers(prose)

    for node_id in sorted(ids):
        if node_id not in in_prose:
            problems.add(
                "orphan-id",
                f"index:{node_id}",
                f"{node_id} is defined in the index but appears nowhere in the report's prose",
                "Add the ID column to the relevant table, or give the identifier a heading. "
                "The index may only project what the prose already states.",
            )

    for token, line_numbers in sorted(in_prose.items()):
        if token not in ids:
            problems.add(
                "undefined-id",
                f"prose:line {line_numbers[0]}",
                f"the prose refers to {token}, which the index does not define "
                f"(seen on line{'s' if len(line_numbers) > 1 else ''} "
                f"{', '.join(str(n) for n in line_numbers[:6])})",
                "Either add it to the index or, if it is not an identifier, rewrite the text "
                "so it does not look like one.",
            )

    cross_check_tiers(index, prose, problems)
    cross_check_testability(index, prose, problems)
    cross_check_metrics(index, prose, problems)


def number_pattern(value):
    """A regex matching how a figure would be written in prose, and nothing wider.

    Integers may carry thousands separators; a report writes 3,178 as often as 3178. The
    boundaries stop 47 from matching inside 470 or 1247, and stop it from matching the 47 in
    47.8 — a figure and a percentage that share leading digits are different figures.
    """
    if isinstance(value, float) and not value.is_integer():
        body = re.escape(f"{value:g}")
    else:
        number = int(value)
        plain = str(number)
        grouped = f"{number:,}"
        body = re.escape(plain) if grouped == plain else f"(?:{re.escape(grouped)}|{re.escape(plain)})"
    return re.compile(rf"(?<![0-9.,]){body}(?![0-9.])")


def find_number(pattern, prose):
    """The first line number where a figure appears in the prose, or None."""
    for number, line in prose:
        if pattern.search(line):
            return number
    return None


def cross_check_metrics(index, prose, problems):
    """Every current figure appears in the prose; no superseded figure does.

    This is the enforcement half of the single-generated-source rule. figures.py makes one
    canonical list and records what each figure used to be; without this check that record
    is a note nobody reads, and the report can go on quoting the old number in prose while
    its tables carry the new one. That is the exact failure the rule exists for, observed in
    a real report.
    """
    metrics = index.get("metrics")
    if not isinstance(metrics, list):
        return

    for i, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            continue
        name = metric.get("name")
        where = f"metrics[{i}] ({name})"
        value = metric.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue

        if find_number(number_pattern(value), prose) is None:
            problems.add(
                "metric-not-in-prose",
                where,
                f"the index carries {name} = {value}, which appears nowhere in the report's "
                "prose",
                "A figure worth putting in the index is worth stating where a reader can see "
                "its basis. Either state it in the prose or drop it from the index.",
            )

        for old in metric.get("superseded") or []:
            if not isinstance(old, (int, float)) or isinstance(old, bool):
                continue
            line = find_number(number_pattern(old), prose)
            if line is None:
                continue
            decisive = (
                isinstance(old, float) and not float(old).is_integer()
            ) or abs(int(old)) >= 100
            message = (
                f"{name} was recomputed from {old} to {value}, and {old} still appears in "
                f"the prose at line {line}"
            )
            fix = (
                "Recomputing an analyser means re-reading the whole report for the old "
                "figure, not only correcting the tables. That is the defect this check "
                "exists for: one report kept token-scanner figures in its recommendation "
                "prose after every table had been corrected."
            )
            if decisive:
                problems.add("superseded-in-prose", f"prose:line {line}", message, fix)
            else:
                problems.advise(
                    "superseded-in-prose",
                    f"prose:line {line}",
                    message
                    + " — reported as an advisory rather than a failure because a value this "
                    "small collides with ordinary text too often to be decisive",
                    fix,
                )


def normalize_label(cell):
    """A table label reduced to something matchable: lowercase, no markdown, no code ticks."""
    text = cell.strip().strip("*`").strip()
    text = re.sub(r"[*`_]", "", text)
    return text.lower().strip()


def label_category(label):
    """Which testability category a Section 8 row label names, or None."""
    for category, needles in TESTABILITY_ROW_PATTERNS:
        if any(needle in label for needle in needles):
            return category
    return None


def parse_count(cell):
    """The integer a count cell states, tolerating thousands separators and emphasis."""
    text = re.sub(r"[*`,\s]", "", cell.strip())
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def parse_share(cell):
    """The percentage a share cell states, or None when it states none (an em dash)."""
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", cell)
    return float(match.group(1)) if match else None


def cross_check_testability(index, prose, problems):
    """The prose's per-category proportions must match the index's entries.

    This is the compensating rule for the one exception to "the index states nothing the
    prose does not". Per-function entries are a machine interface and restating forty-seven
    function names in prose would bury Section 8's actual finding. So the prose states the
    counts and shares, and this recomputes them from the entries. Substituting one
    mechanical check for another keeps the discipline; waiving it would not.
    """
    entries = index.get("testability")
    if not isinstance(entries, list):
        return

    counted = {category: 0 for category in TESTABILITY_CATEGORIES}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("category") in counted:
            counted[entry["category"]] += 1

    table = find_testability_table(prose)
    if table is None:
        if entries:
            problems.add(
                "no-testability-table",
                "prose",
                "the testability index has entries, but no Section 8 table was found "
                "carrying a `Category` column and a count column (`Functions`, `Units`, or "
                "`Count`), so the per-category proportions could not be cross-checked",
                "See references/report-template.md, Section 8. The table is what the index's "
                "per-function entries project from; without it the entries are unstated "
                "analysis.",
            )
        return

    stated_counts, stated_shares, line = table

    for category in sorted(TESTABILITY_CATEGORIES):
        index_count = counted[category]
        prose_count = stated_counts.get(category)
        if prose_count is None:
            if index_count:
                problems.add(
                    "testability-prose-mismatch",
                    f"prose:line {line}",
                    f"the index classifies {index_count} function(s) as {category!r}, and "
                    "the Section 8 table has no row for that category",
                    "Add the row. The index may only project what the prose states, and a "
                    "category present in one and absent from the other is the drift this "
                    "check exists to catch.",
                )
            continue
        if prose_count != index_count:
            problems.add(
                "testability-prose-mismatch",
                f"prose:line {line}",
                f"category {category!r}: the Section 8 table says {prose_count}, the index "
                f"carries {index_count} entr{'y' if index_count == 1 else 'ies'}",
                "The prose is the report. Correct whichever is wrong, but they must agree.",
            )

    # The share column is a share of the classified, non-excluded functions, which is the
    # denominator every real report has used. `excluded` carries no share for that reason.
    denominator = sum(
        count for category, count in counted.items() if category != "excluded"
    )
    if not denominator:
        return
    for category, stated in sorted(stated_shares.items()):
        if category == "excluded" or stated is None:
            continue
        expected = 100.0 * counted[category] / denominator
        if abs(expected - stated) > SHARE_TOLERANCE:
            problems.add(
                "testability-share-mismatch",
                f"prose:line {line}",
                f"category {category!r}: the table states {stated}%, but {counted[category]} "
                f"of {denominator} classified non-excluded functions is {expected:.1f}%",
                "Shares are of the classified functions that are not excluded. Recompute "
                "them from the counts rather than carrying them over from an earlier draft.",
            )


def find_testability_table(prose):
    """Locate Section 8's category table and read it.

    Returns (counts_by_category, shares_by_category, first_line) or None. Rows that map to
    the same category are summed, because one real report splits `needs-seam` across two
    rows naming the two different reasons.
    """
    for header, rows, line in parse_markdown_tables(prose):
        lowered = [normalize_label(h) for h in header]
        if "category" not in lowered:
            continue
        category_column = lowered.index("category")
        count_column = None
        for name in ("functions", "units", "count"):
            for position, cell in enumerate(lowered):
                if cell.startswith(name):
                    count_column = position
                    break
            if count_column is not None:
                break
        if count_column is None:
            continue
        share_column = None
        for position, cell in enumerate(lowered):
            if cell.startswith("share") or cell.startswith("%"):
                share_column = position
                break

        counts = {}
        shares = {}
        for row in rows:
            if len(row) <= max(category_column, count_column):
                continue
            label = normalize_label(row[category_column])
            if not label or any(total in label for total in TESTABILITY_TOTAL_LABELS):
                continue
            category = label_category(label)
            if category is None:
                continue
            count = parse_count(row[count_column])
            if count is None:
                continue
            counts[category] = counts.get(category, 0) + count
            if share_column is not None and len(row) > share_column:
                share = parse_share(row[share_column])
                if share is not None:
                    shares[category] = shares.get(category, 0.0) + share
        if counts:
            return counts, shares, line
    return None


def cross_check_tiers(index, prose, problems):
    """The tier in the index must equal the tier in the prose findings table."""
    findings = {
        f["id"]: f
        for f in index.get("findings", [])
        if isinstance(f, dict) and isinstance(f.get("id"), str)
    }
    if not findings:
        return

    prose_tiers = {}
    table_found = False
    for header, rows, line in parse_markdown_tables(prose):
        lowered = [h.strip().lower() for h in header]
        if "id" not in lowered:
            continue
        risk_column = None
        for name in ("risk", "tier"):
            if name in lowered:
                risk_column = lowered.index(name)
                break
        if risk_column is None:
            continue
        id_column = lowered.index("id")
        table_found = True
        for row in rows:
            if len(row) <= max(id_column, risk_column):
                continue
            candidate = row[id_column].strip().strip("`*")
            if not PROSE_ID.fullmatch(candidate):
                continue
            if candidate.startswith("F"):
                prose_tiers[candidate] = (row[risk_column].strip().strip("*`").lower(), line)

    if not table_found:
        problems.add(
            "no-findings-table",
            "prose",
            "could not find a findings table carrying both an `ID` column and a `Risk` "
            "column, so the index's tiers could not be cross-checked",
            "Add the ID column to the risk-ranked findings table in Section 1.",
        )
        return

    for node_id, finding in sorted(findings.items()):
        if node_id not in prose_tiers:
            problems.add(
                "finding-not-in-table",
                f"index:{node_id}",
                f"{node_id} is not a row of the findings table, so its tier cannot be checked",
            )
            continue
        prose_tier, line = prose_tiers[node_id]
        if prose_tier != finding.get("tier"):
            problems.add(
                "tier-mismatch",
                f"prose:line {line}",
                f"{node_id}: the findings table says {prose_tier!r}, the index says "
                f"{finding.get('tier')!r}",
                "The prose is the report. Correct the index to match it.",
            )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def check(path):
    problems = Problems()
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as error:
        problems.add("unreadable", path, str(error))
        return problems, None

    blocks, prose, code = split_report(text)

    # Runs before the early returns below. An unreproducible command block is a defect in
    # the report whether or not the index parses, and a report with no index at all is
    # exactly the one about to be sent back for backfill — better to report both problems
    # in one pass than to surface the second only after the first is fixed.
    check_reproducible_paths(code, problems)

    if not blocks:
        problems.add(
            "no-index",
            path,
            "the report contains no fenced block with the info string "
            f"`{INDEX_INFO_STRING}`",
            "Add the machine-readable index per references/report-template.md, after the "
            "verification pass. It is section 14 in a report that reconciles a run ledger and "
            "section 13 in one that does not.",
        )
        return problems, None
    if len(blocks) > 1:
        problems.add(
            "duplicate-index",
            path,
            "the report contains "
            f"{len(blocks)} index blocks (lines "
            + ", ".join(str(line) for line, _ in blocks)
            + "); exactly one is permitted",
        )
        return problems, None

    line, body = blocks[0]
    if body is None:
        problems.add("unterminated", f"{path}:{line}", "the index fence is never closed")
        return problems, None

    try:
        index = json.loads(body)
    except json.JSONDecodeError as error:
        problems.add(
            "invalid-json",
            f"{path}:{line + error.lineno}",
            f"the index block is not valid JSON: {error.msg} (column {error.colno})",
        )
        return problems, None

    if not isinstance(index, dict):
        problems.add("field-type", f"{path}:{line}", "the index must be a JSON object")
        return problems, None

    ids = validate_schema(index, problems)
    cross_check_prose(index, prose, ids, problems)
    return problems, index


def check_ledger(report_path, ledger_path, problems):
    """R-7.2: every open run-ledger item is confirmed, updated, or contested — never dropped.

    The comparison itself lives in the reporting skill's `reconcile.py` and is imported rather
    than reimplemented here. This is the only place in the suite where a later stage's code
    runs inside an earlier one, and the alternative was a second implementation of one rule,
    which is a second opinion about what the rule says.

    The dependency is optional and one-directional: only this flag reaches for it, and a
    missing reporting skill is reported as such rather than surfacing as an ImportError.
    """
    import os  # noqa: PLC0415

    here = os.path.dirname(os.path.abspath(__file__))
    reporting = os.path.join(
        os.path.dirname(os.path.dirname(here)), "test-reporting", "scripts"
    )
    module_path = os.path.join(reporting, "reconcile.py")
    if not os.path.isfile(module_path):
        problems.add(
            "reporting-skill-absent",
            report_path,
            "--ledger needs the test-reporting skill installed beside this one, and it is "
            f"not at {reporting}",
            "The run ledger is stage four's artifact and the reconciliation check is stage "
            "four's code. Install `test-reporting` alongside this skill. Do not reimplement "
            "the comparison here: two implementations of one rule are two opinions about what "
            "the rule says.",
        )
        return

    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("test_reporting_reconcile", module_path)
    reconcile = importlib.util.module_from_spec(spec)
    sys.modules["test_reporting_reconcile"] = reconcile
    if reporting not in sys.path:
        sys.path.insert(0, reporting)
    spec.loader.exec_module(reconcile)

    try:
        found, open_count = reconcile.run(ledger_path, report_path)
    except reconcile.ReconcileError as error:
        problems.add("ledger-unreadable", report_path, str(error))
        return

    for problem in found:
        problems.add(
            problem["rule"],
            f"{report_path} ({problem.get('item') or 'reconciliation'})",
            problem["message"],
            problem.get("fix"),
        )
    if not found and open_count:
        problems.advise(
            "ledger-reconciled",
            report_path,
            f"all {open_count} open run-ledger item(s) are confirmed, updated, or contested",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("report", help="path to the assessment report")
    parser.add_argument(
        "--ledger",
        help="path to docs/test-ledger.json. R-7.2 of the reporting document makes an open "
             "ledger item that this report does not confirm, update, or contest a failure — "
             "the only mechanism under which an open defect provably cannot vanish between "
             "runs",
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args()

    problems, index = check(args.report)
    if args.ledger:
        check_ledger(args.report, args.ledger, problems)

    if args.json:
        print(
            json.dumps(
                {
                    "report": args.report,
                    "ok": len(problems) == 0,
                    "problem_count": len(problems),
                    "problems": problems.items,
                    "advisories": problems.advisories,
                    "summary": summarize(index) if index else None,
                },
                indent=2,
            )
        )
    else:
        if not problems:
            print(f"ok: {args.report}")
            if index:
                summary = summarize(index)
                print(
                    "  {findings} findings, {recommendations} recommendations, "
                    "{exclusions} exclusions, {degradations} degradations, "
                    "{open_questions} open questions, {dependencies} dependency edges".format(
                        **summary
                    )
                )
                if summary["contested"]:
                    print(f"  {summary['contested']} contested item(s)")
        else:
            print(f"FAILED: {args.report} — {len(problems)} problem(s)\n")
            for problem in problems.items:
                print(f"  [{problem['rule']}] {problem['where']}")
                print(f"      {problem['message']}")
                if problem["fix"]:
                    print(f"      fix: {problem['fix']}")
            print()

        if problems.advisories:
            print(
                f"  {len(problems.advisories)} advisory(ies) — read these, they do not fail "
                "the report:"
            )
            for advisory in problems.advisories:
                print(f"    [{advisory['rule']}] {advisory['where']}")
                print(f"        {advisory['message']}")
            print()

    return 0 if not problems else 1


def summarize(index):
    contested = 0
    for section in ("findings", "recommendations", "exclusions"):
        for item in index.get(section, []) or []:
            if isinstance(item, dict) and item.get("contested"):
                contested += 1
    return {
        "findings": len(index.get("findings") or []),
        "recommendations": len(index.get("recommendations") or []),
        "exclusions": len(index.get("exclusions") or []),
        "degradations": len(index.get("degradations") or []),
        "open_questions": len(index.get("open_questions") or []),
        "dependencies": len(index.get("dependencies") or []),
        "contested": contested,
    }


if __name__ == "__main__":
    sys.exit(main())

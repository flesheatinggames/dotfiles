#!/usr/bin/env python3
"""R-5.1's checker: every number in the report traces to the run record, or the assembly fails.

The single-generated-source rule, applied to the report itself. Stage one learned it the hard
way — a report kept token-scanner function counts in its prose after the analyser correction had
recomputed every figure in its tables, so it stated two different counts and only the tables
were right. Correcting the tables is the half of the job people do.

**Two checks, and the first is the stronger one.** The report is regenerated from the run record
and compared against the file on disk with the prose slots masked out. Every table, every
figure, every heading has to be byte-identical to what the record produces right now. That
proves the tables were not edited *and* that the record has not moved under the report since it
was written, which no amount of number-matching could establish. Then, within the prose slots
only, every number is checked against the record's figure set.

**The division of labour is what keeps this checker alive.** A checker that fires on legitimate
writing gets switched off, and then the rule is gone with nothing announcing it. So the model's
numbers are rare by construction: everything countable is already in a table above the paragraph
that discusses it, and the writer's job is to say what the tables mean. Within the slots the
exemptions are generous and specific — identifiers, dates, requirement numbers, commit hashes,
version numbers, fenced blocks, and code spans carrying a letter or a path separator. What is
left is a bare numeral in a sentence, which is exactly the thing that has to come from somewhere.

**Writing outside the slots is a failure, and that is deliberate.** It shows up as a difference
against the regenerated skeleton. If a slot is the wrong shape for something that needs saying,
that is a problem with the report template, to be fixed there so every later report inherits the
fix — not worked around in one report where nobody will find it again.

**Both directions of failure matter and only one is obvious.** A number that is not in the
record may be invented. A number that *is* in the record may still be the wrong one for the
sentence it sits in — this checker cannot see that, and the plain-language reader described in
`references/plain-language-brief.md` is what stands where this cannot.

Usage:
    python3 trace_report.py docs/test-report.md --repo .
    python3 trace_report.py docs/test-report.md --record run-record.json --json
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_record  # noqa: E402
import siblings  # noqa: E402

planlib = siblings.planlib()

# ---- what is not a figure -------------------------------------------------------------
#
# Each of these is a number that carries no quantitative claim: it names something, dates
# something, or points at something. Substituted out before anything is checked, in this order,
# because a later pattern would otherwise match the tail of an earlier one.

_EXEMPT = (
    # Requirement and rule references: R-5.1, R-11.3.
    re.compile(r"\bR-\d+(?:\.\d+)*\b"),
    # ISO dates and timestamps.
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?\b"),
    # Identifiers with a dashed number: WI-01, DF-1, PF-03, DA-1, CO-2, DEC-01, BL-1, PX-2.
    re.compile(r"\b[A-Z][A-Za-z]{0,4}-\d+\b"),
    # Identifiers with a bare number: C5, S0, E1, F3, R2, X1, Q1, D1.
    re.compile(r"\b[A-Z]\d+\b"),
    # Schema and tool versions written as `version 1.2` or `1.0`.
    re.compile(r"\bversion \d+(?:\.\d+)*\b"),
    # Commit hashes: hex, at least seven characters, containing at least one hex letter so a
    # seven-digit figure is not silently exempted.
    re.compile(r"\b(?=[0-9a-f]{7,40}\b)[0-9a-f]*[a-f][0-9a-f]*\b"),
    # A file path with a line number, and paths generally.
    re.compile(r"\b[\w.\-/]+\.[A-Za-z]{1,5}(?::\d+)?\b"),
    # A cross-reference to one of this report's own sections. It points somewhere; it does not
    # count anything. This was missing until a rewrite happened to say "section 9", which is not
    # in the record — while "section 8" a paragraph earlier had been passing all along because
    # the run had eight work items. An exemption that holds by coincidence is worse than one
    # that is absent, because nothing reveals it until the coincidence breaks.
    re.compile(r"(?i)\bsections?\s+\d+(?:\s*(?:,|and|to|–|—)\s*\d+)*"),
    # Markdown heading numbers and ordered-list markers.
    re.compile(r"(?m)^#{1,6}\s+\d+\.\s"),
    re.compile(r"(?m)^\s*\d+\.\s"),
    # Table alignment rows.
    re.compile(r"(?m)^\|[\s\-:|]+\|$"),
)

_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%?)")

# A code span is exempt when it is quoting something rather than stating a figure. Quoting
# means it carries a letter, a path separator, or a colon — a file, a command, a test name, a
# branch. `78.89%` in backticks is none of those and is checked like any other number.
_QUOTING_RE = re.compile(r"[A-Za-z/:]")


def strip_fenced_blocks(text):
    """Remove fenced code blocks. Their contents are machine output, not the report's prose."""
    out = []
    fence = None
    for line in text.split("\n"):
        match = _FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(2)
                out.append("")
                continue
            out.append(line)
            continue
        if match and match.group(2)[0] == fence[0] and len(match.group(2)) >= len(fence):
            fence = None
        out.append("")
    return "\n".join(out)


def strip_prose_briefs(text):
    """Remove the unfilled `> **To write:**` briefs assemble.py leaves behind.

    A report still carrying them is not finished, which is reported separately. Their own text
    must not be traced, because it is instructions rather than findings.
    """
    return re.sub(r"(?m)^> \*\*To write:\*\*.*(?:\n(?!<!--).*)*", "", text)


def blank(match):
    return " " * len(match.group(0))


def scrub(text):
    """Replace every exempt construct with spaces, preserving offsets so lines still line up."""
    text = strip_fenced_blocks(text)
    text = strip_prose_briefs(text)
    text = _CODE_SPAN_RE.sub(
        lambda m: " " * len(m.group(0)) if _QUOTING_RE.search(m.group(1)) else m.group(0),
        text,
    )
    for pattern in _EXEMPT:
        text = pattern.sub(blank, text)
    return text


_SLOT_RE = re.compile(
    r"<!-- PROSE (?P<name>[\w-]+) —.*?-->\n(?P<body>.*?)<!-- END PROSE (?P=name) -->",
    re.DOTALL,
)


def slot_bodies(report_text):
    """Each prose slot's body, with the file line its first character sits on."""
    out = []
    for match in _SLOT_RE.finditer(report_text):
        line = report_text[: match.start("body")].count("\n") + 1
        out.append((match.group("name"), match.group("body"), line))
    return out


def mask_slots(report_text):
    """The report with every prose body replaced by a fixed marker.

    What remains is the skeleton: everything `assemble.py` generated. Masking rather than
    deleting keeps the comparison honest about structure — a report that lost a whole slot
    differs from one whose slot is empty.
    """
    return _SLOT_RE.sub(
        lambda m: f"<!-- PROSE {m.group('name')} -->\n\x00\n<!-- END PROSE {m.group('name')} -->",
        report_text,
    )


def skeleton_differences(report_text, skeleton_text):
    """The first few lines where the report's generated regions differ from a fresh assembly."""
    actual = mask_slots(report_text).split("\n")
    expected = mask_slots(skeleton_text).split("\n")
    out = []
    for index in range(max(len(actual), len(expected))):
        got = actual[index] if index < len(actual) else "<end of file>"
        want = expected[index] if index < len(expected) else "<end of file>"
        if got != want:
            out.append({"line": index + 1, "found": got[:160], "expected": want[:160]})
        if len(out) >= 8:
            break
    return out


def untraceable(report_text, figure_set):
    """Every number in a prose slot that the run record does not contain.

    Only the slots. Everything else in the file is generated, and it is checked by being
    regenerated rather than by having its numbers matched — which is the stronger check, since
    a generated table can quote a diagnosis containing a number that is nobody's figure.
    """
    problems = []
    lines = report_text.split("\n")
    for name, body, first_line in slot_bodies(report_text):
        scrubbed = scrub(body)
        for number, offset in _numbers_with_lines(scrubbed):
            if _normalise(number) in figure_set:
                continue
            line = first_line + offset - 1
            problems.append({
                "slot": name,
                "line": line,
                "number": number,
                "context": lines[line - 1].strip()[:160] if line <= len(lines) else "",
            })
    return problems


def _numbers_with_lines(text):
    out = []
    for index, line in enumerate(text.split("\n"), start=1):
        for match in _NUMBER_RE.finditer(line):
            out.append((match.group(1), index))
    return out


def _normalise(text):
    number = float(text)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def unfilled_slots(report_text):
    """Prose slots still holding their brief rather than a paragraph."""
    return [
        name
        for name, body, _ in slot_bodies(report_text)
        if "**To write:**" in body or not body.strip()
    ]


def forbidden_shapes(report_text):
    """R-5.6: no scalar grade, score, or letter anywhere in the report.

    The report exists to earn the sentence "you can run this suite and trust it", and that
    sentence is not true as a scalar. A grade is the report-level version of the vanity coverage
    number this whole project exists to kill: it compresses a bounded map with marked voids
    into one symbol that hides exactly the voids.
    """
    problems = []
    patterns = (
        (r"(?i)\b(?:overall|final|suite|trust|confidence|quality)\s+(?:grade|score|rating)\b",
         "a scalar grade"),
        (r"(?i)\bgrade[:\s]+[A-F][+-]?\b", "a letter grade"),
        (r"(?i)\b(?:score|rating)[:\s]+\d+\s*(?:/|out of)\s*\d+\b", "a score out of a total"),
        (r"(?i)\b\d+\s*(?:/|out of)\s*(?:10|100)\s+(?:overall|confidence|trust)\b",
         "a confidence score"),
        (r"(?i)\bproduction[- ]ready\b", "an unbounded readiness claim"),
        (r"(?i)\bfully (?:tested|covered|verified)\b", "an unbounded coverage claim"),
    )
    for index, line in enumerate(report_text.split("\n"), start=1):
        if line.lstrip().startswith("<!--") or "**To write:**" in line:
            continue
        for pattern, what in patterns:
            if re.search(pattern, line):
                problems.append({"line": index, "what": what, "context": line.strip()[:160]})
    return problems


def load_record(plan, record_path, repo):
    if record_path:
        with open(record_path, encoding="utf-8") as handle:
            return json.load(handle)
    sidecar = os.path.join(repo, run_record.DEFAULT_LOG_DIR, "run-record.json")
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as handle:
            return json.load(handle)
    if plan is not None and plan.record_block is not None:
        return planlib.to_plain(plan.record_block.node)
    return None


def regenerate(record, plan, repo, plan_path, ledger_path, report_path):
    """The report as `assemble.py` would write it from the record as it now stands."""
    import assemble  # noqa: PLC0415
    import ledger as ledger_module  # noqa: PLC0415

    full = ledger_path if os.path.isabs(ledger_path) else os.path.join(repo, ledger_path)
    try:
        ledger_data = ledger_module.load(full)
    except ledger_module.LedgerError:
        ledger_data = None
    repository = (
        (plan.meta.node.get("repository") if plan.meta else None)
        or os.path.basename(os.path.abspath(repo))
    )
    # Regenerate with the report's own prose in place, so the comparison is about the
    # generated regions alone rather than about the slots being empty.
    return assemble.build(
        record, plan, ledger_data, repository, plan_path,
        assemble.existing_prose(report_path),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("report")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--record", help="a run-record JSON file")
    parser.add_argument("--plan", default="docs/test-plan.md",
                        help="the plan the report was assembled from; needed to regenerate the "
                             "skeleton and prove the generated regions were not edited")
    parser.add_argument("--ledger", default=run_record.DEFAULT_LEDGER)
    parser.add_argument("--phase", default="closed", choices=("executed", "closed"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report_path = (
        args.report if os.path.isabs(args.report) else os.path.join(args.repo, args.report)
    )
    try:
        with open(report_path, encoding="utf-8") as handle:
            report_text = handle.read()
    except OSError as error:
        print(f"cannot read {args.report}: {error}", file=sys.stderr)
        return 2

    plan = None
    plan_path = (
        args.plan if os.path.isabs(args.plan) else os.path.join(args.repo, args.plan)
    )
    if os.path.exists(plan_path):
        planio = siblings.planio()
        plan = planio.Plan(plan_path, phase=args.phase, lint_writes=False)

    record = load_record(plan, args.record, args.repo)
    if record is None:
        print(
            "no run record found. Pass --record, or run run_record.py --write so the sidecar "
            "at docs/test-execution-log/run-record.json exists. Without it there is nothing to "
            "trace against, and a report nobody traced is indistinguishable from one that "
            "passed.",
            file=sys.stderr,
        )
        return 2

    figure_set = run_record.figures(record)
    problems = untraceable(report_text, figure_set)
    unfilled = unfilled_slots(report_text)
    forbidden = forbidden_shapes(report_text)

    edits = []
    if plan is not None:
        edits = skeleton_differences(
            report_text,
            regenerate(record, plan, args.repo, args.plan, args.ledger, report_path),
        )

    ok = not (problems or unfilled or forbidden or edits)

    if args.json:
        print(json.dumps({
            "ok": ok,
            "untraceable": problems,
            "unfilled_slots": unfilled,
            "forbidden_shapes": forbidden,
            "generated_regions_edited": edits,
            "skeleton_checked": plan is not None,
            "figures_in_record": len(figure_set),
        }, indent=2, ensure_ascii=False))
        return 0 if ok else 1

    if ok:
        print(f"ok: {args.report} — every number in the prose traces to the run record "
              f"({len(figure_set)} figure(s) available)")
        if plan is None:
            print(f"  note: {args.plan} was not found, so the generated regions were not "
                  "regenerated and compared. That is the stronger of the two checks; run this "
                  "again with --plan pointing at the plan.")
        else:
            print("  and every generated table is byte-identical to a fresh assembly from the "
                  "record")
        return 0

    print(f"FAILED: {args.report}\n")
    if edits:
        print(f"  the generated regions differ from a fresh assembly from the run record, at "
              f"{len(edits)} line(s):")
        for edit in edits:
            print(f"    line {edit['line']}")
            print(f"      found:    {edit['found']}")
            print(f"      expected: {edit['expected']}")
        print()
        print("  Either a table was edited by hand — which R-5.1 forbids, because the report "
              "would then state two things and only the record would be right — or the record "
              "changed after the report was assembled. Re-run assemble.py and rewrite the "
              "prose slots into the fresh skeleton.")
        print()
    if unfilled:
        print(f"  {len(unfilled)} prose slot(s) still hold their brief rather than a "
              "paragraph:")
        for name in unfilled:
            print(f"    {name}")
        print()
    if forbidden:
        print(f"  {len(forbidden)} forbidden shape(s). R-5.6 permits no scalar grade, score, "
              "or letter, and no unbounded claim:")
        for problem in forbidden:
            print(f"    line {problem['line']}: {problem['what']} — {problem['context']}")
        print()
    if problems:
        print(f"  {len(problems)} number(s) in the prose do not appear in the run record:")
        for problem in problems:
            print(f"    line {problem['line']} (slot `{problem['slot']}`): "
                  f"{problem['number']} — {problem['context']}")
        print()
        print("  R-5.1: a number that fails the trace fails the assembly. Either the figure is "
              "in a table above the sentence and should be quoted from there, or it is not in "
              "the record at all — in which case nothing computed it and it must not be "
              "stated. Do not add it to the record to make this pass; the record is derived.")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())

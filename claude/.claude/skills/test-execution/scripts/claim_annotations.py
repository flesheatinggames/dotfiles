#!/usr/bin/env python3
"""The claim annotation convention, and the per-item check that every claim has a test.

R-5.7 requires tests to be annotated with the claim identifiers they assert, in a
machine-readable form, and leaves the form to this skill to define once. This is it:

    # claim: C12                     Python, Ruby, shell
    // claim: C12                    TypeScript, JavaScript, Go, Java, C
    /* claim: C12, C13 */            block-comment languages
    <!-- claim: C12 -->              Markdown-ish

**A comment rather than a test-name convention**, and the choice is not arbitrary. A name
like `test_c12_case_3` is machine-readable and unreadable: the plan's mutation checks name
tests by name, the owner reads those names at the review gate, and a gate full of identifiers
is a gate nobody reads carefully. A comment carries the identifier without spending the name,
and it survives a rename of either the test or the file.

The check this enables is structural and knows it (R-8.1): it proves every claim has a test
and proves nothing about whether the test is any good. Mutation checks and the R-8.3 verifier
are what judge that.

Usage:
    python3 claim_annotations.py --repo . --files tests/test_money.py --claims C1 C2
    python3 claim_annotations.py --repo . --plan docs/test-plan.md --item WI-04 --json
"""

import argparse
import json
import os
import re
import sys

# `claim:` then one or more identifiers separated by commas or spaces. The trailing text is
# ignored, so `# claim: C12 — the German separator case` is legal and reads well.
_ANNOTATION = re.compile(
    r"(?:#|//|/\*|<!--|--|;)\s*claims?\s*:\s*(?P<ids>C[0-9]+(?:\s*[, ]\s*C[0-9]+)*)",
    re.IGNORECASE,
)
_CLAIM_ID = re.compile(r"C[0-9]+")

# What a test definition looks like. Deliberately broad: this runs over test files, where a
# false positive costs nothing and a miss means a claim looks unasserted.
_TEST_DEFINITION = re.compile(
    r"""
    ^\s*(?:
        (?:async\s+)?def\s+(?P<py>test\w*)            # pytest, unittest
      | (?:it|test)\s*(?:\.\w+)?\s*\(\s*             # vitest, jest, mocha
        (?P<quote>['"`])(?P<js>.*?)(?P=quote)
      | func\s+(?P<go>Test\w+)\s*\(                  # go
      | (?:public\s+)?void\s+(?P<java>test\w*)\s*\(  # junit
    )
    """,
    re.VERBOSE,
)

# How far below an annotation the test it annotates may start. Enough for a decorator stack or
# a blank line; short enough that an annotation at the top of a file does not silently claim
# the first test in it.
LOOKAHEAD = 6


def annotation_line(claim_ids, comment="#"):
    """Render the annotation, so the skill's documentation and its checker cannot disagree."""
    return f"{comment} claim: {', '.join(claim_ids)}"


def scan(text):
    """Every annotated test in one file: [{"claims": [...], "test": name, "line": n}].

    An annotation attaches to the next test definition within ``LOOKAHEAD`` lines. Where there
    is none — the annotation sits inside a test body, which is where people naturally put it —
    it attaches to the enclosing test instead. Both placements are common and both are
    correct; a checker that accepted only one would push people toward the other and then
    report their claims as unasserted.
    """
    lines = text.split("\n")
    tests = []
    for index, line in enumerate(lines):
        match = _TEST_DEFINITION.match(line)
        if match:
            name = next(
                (value for key, value in match.groupdict().items()
                 if key != "quote" and value),
                None,
            )
            if name:
                tests.append({"name": name, "line": index + 1, "claims": []})

    by_line = {test["line"]: test for test in tests}
    starts = sorted(by_line)

    for index, line in enumerate(lines):
        found = _ANNOTATION.search(line)
        if not found:
            continue
        claims = _CLAIM_ID.findall(found.group("ids").upper())
        here = index + 1

        following = [start for start in starts if here < start <= here + LOOKAHEAD]
        if following:
            by_line[following[0]]["claims"].extend(claims)
            continue
        preceding = [start for start in starts if start <= here]
        if preceding:
            by_line[preceding[-1]]["claims"].extend(claims)

    return [test for test in tests if test["claims"]]


def scan_files(repo, paths):
    """Annotated tests across a set of repository-relative files, keyed by claim."""
    by_claim = {}
    scanned = []
    missing = []
    for path in paths:
        full = os.path.join(repo, path)
        if not os.path.isfile(full):
            missing.append(path)
            continue
        with open(full, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        scanned.append(path)
        for test in scan(text):
            for claim_id in test["claims"]:
                by_claim.setdefault(claim_id, []).append(
                    {"file": path, "test": test["name"], "line": test["line"]}
                )
    return by_claim, scanned, missing


def check(repo, paths, claims):
    """The per-item check of R-5.7. Returns a record in the recorded-check shape."""
    by_claim, scanned, missing = scan_files(repo, paths)
    unasserted = [claim_id for claim_id in claims if claim_id not in by_claim]

    record = {
        "kind": "claim-annotations",
        "files_scanned": scanned,
        "files_missing": missing,
        "by_claim": by_claim,
        "unasserted": unasserted,
    }

    if missing and not scanned:
        record["outcome"] = "not-run"
        record["detail"] = (
            "none of the item's declared test files exist yet, so nothing could be scanned: "
            + ", ".join(missing)
        )
        return record

    if unasserted:
        record["outcome"] = "failed"
        record["detail"] = (
            f"{len(unasserted)} claim(s) the item asserts have no annotated test: "
            + ", ".join(unasserted)
            + ". Annotate the test that asserts each with a `claim:` comment — "
            + annotation_line(unasserted[:2])
            + " — above the test or as its first line. If there is genuinely no such test, "
            "the item is not done."
        )
        return record

    record["outcome"] = "passed"
    record["detail"] = (
        f"{len(claims)} claim(s) each asserted by at least one annotated test across "
        f"{len(scanned)} file(s)."
    ) + (
        f" {len(missing)} declared test file(s) do not exist and were skipped: "
        + ", ".join(missing)
        if missing
        else ""
    )
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=".")
    parser.add_argument("--files", nargs="*", default=[], help="repository-relative test files")
    parser.add_argument("--claims", nargs="*", default=[], help="claim identifiers to require")
    parser.add_argument("--plan", help="take the files and claims from a plan item instead")
    parser.add_argument("--item", help="the work item, with --plan")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths, claims = list(args.files), list(args.claims)
    if args.plan:
        if not args.item:
            parser.error("--plan requires --item")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import planio  # noqa: PLC0415

        plan = planio.Plan(args.plan, lint_writes=False)
        node = plan.node("work-item", args.item).node
        paths = [p for p in ((node.get("files-touched") or {}).get("test") or [])]
        claims = list(node.get("claims") or [])

    record = check(args.repo, paths, claims)
    if args.json:
        print(json.dumps(record, indent=2, ensure_ascii=False))
    else:
        print(f"{record['outcome']}: {record['detail']}")
        for claim_id in sorted(record["by_claim"]):
            for entry in record["by_claim"][claim_id]:
                print(f"  {claim_id}  {entry['file']}:{entry['line']}  {entry['test']}")
    return 0 if record["outcome"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

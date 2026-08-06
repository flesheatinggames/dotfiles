#!/usr/bin/env python3
"""Read a plan into run state, and write execution results back into it in place.

This is the foundation piece. Stage two's requirements described the writeback contract as "a
capability check against the existing writer"; there is no writer, and this is it. What stage
two provides is the mechanism rather than the facility: ``planlib``'s parser records the file
line of every key in ``MapNode.value_spans``, and nothing consumed those positions until now.

**Why in place rather than a results file.** Stage two established the plan as the running
record the stage four report is built from. A separate results document would have been
easier to write and would mean two files that can disagree about what happened — and the one
a person opens is the plan.

**Why byte-exactness matters.** The plan the executor writes into is the plan the owner
reviewed, with their comments in it. Rewriting one ``status:`` line must not disturb a byte
around it. That is the whole reason this rewrites spans rather than re-serialising the
document: a round trip through any YAML emitter would return a technically equivalent file
with every comment gone and every folded scalar refolded, and the owner would have no way to
see what execution actually changed.

**Every write is re-linted and rolled back on failure.** Stage three's entry gate is stage
two's linter (R-4.2), so a write the linter rejects is a write that must never land. The
check is relative to a baseline captured at load: a plan that already had a problem can still
be written to, and only problems the write *introduced* roll it back. In practice the
baseline is empty, because pre-flight refuses to start a run on a plan that does not lint.

Usage:
    python3 planio.py <plan> --show                    # the run state, as JSON
    python3 planio.py <plan> --set WI-04 status done   # one field, re-linted
    python3 planio.py <plan> --selftest                # the bundled round-trip tests
"""

import argparse
import contextlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import siblings  # noqa: E402

planlib = siblings.planlib()


# --------------------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------------------


class WriteRejected(Exception):
    """A write was rolled back because it introduced lint failures.

    Carries the problems so the caller can report what the plan would have said, rather than
    only that something went wrong.
    """

    def __init__(self, description, problems):
        self.description = description
        self.problems = problems
        super().__init__(self.report())

    def report(self):
        lines = [f"the write was rejected and rolled back: {self.description}", ""]
        lines += [f"  {problem}" for problem in self.problems]
        lines.append("")
        lines.append(
            "  The plan file is unchanged. Stage three's entry gate is stage two's linter "
            "(R-4.2), so a write the linter rejects is a write that must never land — "
            "leaving it in place would produce a plan nobody could lint and therefore a "
            "record nobody could trust."
        )
        return "\n".join(lines)


class PlanNotFound(Exception):
    """A block or key the caller named does not exist in the plan."""


# --------------------------------------------------------------------------------------
# Emitting the YAML subset
# --------------------------------------------------------------------------------------

# Characters that make a plain scalar ambiguous at the start of a value.
_NEEDS_QUOTE_START = set("-?:,[]{}#&*!|>'\"%@`")
_NUMERIC_RE = re.compile(r"^[-+]?(?:[0-9][0-9_]*|(?:[0-9]*\.[0-9]+|[0-9]+\.[0-9]*)(?:[eE][-+]?[0-9]+)?)$")

# Where a folded scalar wraps. Wide enough that most sentences survive intact and narrow
# enough that the plan stays readable in a terminal beside the code it describes.
FOLD_WIDTH = 92


def render_scalar(value):
    """One scalar, quoted only where a plain form would be ambiguous."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)

    text = str(value)
    if (
        text == ""
        or text != text.strip()
        or text[0] in _NEEDS_QUOTE_START
        or text in planlib._AMBIGUOUS_BOOLS
        or text in ("null", "true", "false", "~")
        or _NUMERIC_RE.match(text)
        # A bare date or timestamp is a `datetime` to PyYAML's implicit resolver and a string
        # here, which the R-11.1 cross-check reports as a whole-block disagreement. Every
        # timestamp this stage writes goes through here, so quoting them is the writer's job
        # rather than something each caller has to remember.
        or planlib._DATE_LIKE.match(text)
        or ": " in text
        or text.endswith(":")
        or " #" in text
    ):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _fold(text, indent):
    """Wrap one paragraph into the body of a `>` folded scalar."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if current and len(candidate) + indent > FOLD_WIDTH:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_field(key, value, indent=0):
    """The lines for one `key: value` pair, in the plan's YAML subset.

    Three shapes for a string, and the choice between them is not cosmetic:

    * a short single-line string goes inline;
    * a long single-line string becomes a `>` folded scalar, which is the plan's house style
      and reads as prose;
    * a string **containing newlines** becomes a `|` literal scalar, because folding would
      silently replace those newlines with spaces. A writer that quietly changes the value it
      was asked to store is the one failure mode this module cannot be allowed to have.
    """
    pad = " " * indent
    lines = []

    if isinstance(value, dict):
        lines.append(f"{pad}{key}:")
        if not value:
            lines[-1] += " {}"
            return lines
        for sub_key, sub_value in value.items():
            lines.extend(render_field(sub_key, sub_value, indent + 2))
        return lines

    if isinstance(value, list):
        lines.append(f"{pad}{key}:")
        if not value:
            lines[-1] += " []"
            return lines
        for entry in value:
            lines.extend(_render_sequence_entry(entry, indent + 2))
        return lines

    if isinstance(value, str):
        # A trailing newline is chomping, not content. A folded scalar reads back as one long
        # line plus the newline its clip chomping added, and testing the raw value for "\n"
        # would call that multi-line and re-render it as a literal block — turning a neatly
        # folded paragraph into one enormous line the next time anything rewrote it. Strip it
        # before deciding which style the value actually needs.
        body = value.rstrip("\n")
        if "\n" in body:
            lines.append(f"{pad}{key}: |")
            for line in body.split("\n"):
                lines.append(f"{pad}  {line}" if line else "")
            return lines
        if len(body) + len(key) + indent + 2 > FOLD_WIDTH:
            lines.append(f"{pad}{key}: >")
            for line in _fold(body, indent + 2):
                lines.append(f"{pad}  {line}")
            return lines

    lines.append(f"{pad}{key}: {render_scalar(value)}")
    return lines


def _render_sequence_entry(entry, indent):
    pad = " " * indent
    if isinstance(entry, dict):
        if not entry:
            return [f"{pad}- {{}}"]
        rendered = []
        for i, (key, value) in enumerate(entry.items()):
            block = render_field(key, value, indent + 2)
            if i == 0:
                block[0] = f"{pad}- " + block[0][indent + 2 :]
            rendered.extend(block)
        return rendered
    if isinstance(entry, list):
        raise ValueError("a sequence directly inside a sequence is not part of this subset")
    if isinstance(entry, str) and ("\n" in entry or len(entry) + indent + 2 > FOLD_WIDTH):
        # A long free-text entry in a list. Fold it under the dash rather than overflowing.
        rendered = [f"{pad}- >"]
        for line in _fold(entry.replace("\n", " "), indent + 4):
            rendered.append(f"{pad}    {line}")
        return rendered
    return [f"{pad}- {render_scalar(entry)}"]


def render_block(kind, fields):
    """A whole fenced block, ready to insert."""
    lines = [f"```yaml {kind}"]
    for key, value in fields.items():
        lines.extend(render_field(key, value))
    lines.append("```")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------------------

# Section titles the writeback creates, in the order they are appended. They sit at the end of
# the plan rather than beside the material they describe, because inserting a defect entry
# next to its work item would push every line below it and make the owner's review comments
# harder to find, not easier.
LOG_SECTION = "Execution log"
DEFECT_SECTION = "Defect registry"
SUMMARY_SECTION = "Run summary"

# Stage four appends after those three, in the order the close-out gate produces them: the
# decisions first, then the disputes the owner looked at without being obliged to answer, then
# what the run says about the pipeline, then the derived record of all of it.
CLOSEOUT_SECTION = "Close-out decisions"
DISPUTE_SECTION = "Dispute decisions"
FINDING_SECTION = "Pipeline findings"
RECORD_SECTION = "Run record"

_HEADING_RE = re.compile(r"^##\s+(?:(\d+)\.\s*)?(.+?)\s*$")


class Plan:
    """A plan file, its parsed run state, and the writes stage three makes to it."""

    def __init__(self, path, assessment=None, phase="executed", lint_writes=True):
        self.path = path
        self.assessment = assessment
        self.phase = phase
        self.lint_writes = lint_writes
        self._plan_lint = siblings.plan_lint() if lint_writes else None
        self.text = ""
        self.reload()
        self.baseline = self._problem_keys() if lint_writes else set()

    # ---- reading ---------------------------------------------------------------------

    def reload(self):
        with open(self.path, encoding="utf-8") as handle:
            self.text = handle.read()
        problems = []
        self.blocks = planlib.parse_blocks(self.text, self.path, problems)
        self.parse_problems = problems

        self.by_kind = {}
        for block in self.blocks:
            self.by_kind.setdefault(block.kind, []).append(block)

        self.meta = self._single("plan-meta")
        self.target = self._single("target")
        self.summary_block = self._single("run-summary")
        self.record_block = self._single("run-record")
        self.items = self._by_id("work-item")
        self.slices = self._by_id("slice")
        self.claims = self._by_id("claim")
        self.defects = self._by_id("defect")
        # Stage four's blocks. They are indexed here rather than in the reporting skill for the
        # same reason the execution writeback is defined in the planning schema: this module is
        # the one writer, and a block it cannot address is a block nothing can rewrite in place.
        self.closeouts = self._by_id("close-out")
        self.findings = self._by_id("pipeline-finding")
        self.blockers = {}
        for kind in ("escalation", "decision"):
            self.blockers.update(self._by_id(kind))

    def _single(self, kind):
        found = self.by_kind.get(kind, [])
        return found[0] if found else None

    def _by_id(self, kind):
        out = {}
        for block in self.by_kind.get(kind, []):
            node_id = block.node.get("id") if block.node else None
            if isinstance(node_id, str):
                out[node_id] = block
        return out

    def node(self, kind, block_id):
        table = {
            "work-item": self.items,
            "slice": self.slices,
            "claim": self.claims,
            "defect": self.defects,
            "close-out": self.closeouts,
            "pipeline-finding": self.findings,
        }.get(kind)
        if table is None or block_id not in table:
            raise PlanNotFound(f"no `{kind}` block with id {block_id!r} in {self.path}")
        return table[block_id]

    # ---- run state -------------------------------------------------------------------

    def run_state(self):
        """Everything the loop needs, in the order it needs it.

        Slices in plan order, items within a slice in dependency order. R-5.1 states the
        ordering rule; computing it here means the executor never derives it, and two runs of
        the same plan cannot disagree about what comes next.
        """
        return {
            "plan": self.path,
            "repository": (self.meta.node.get("repository") if self.meta else None),
            "assessment_commit": (
                self.meta.node.get("assessment_commit") if self.meta else None
            ),
            "approved": bool(self.meta and self.meta.node.get("approved")),
            "slices": [
                {
                    "id": slice_id,
                    "title": self.slices[slice_id].node.get("title"),
                    "items": self.ordered_items(slice_id),
                }
                for slice_id in self.slice_order()
            ],
            "items": {
                item_id: {
                    "type": block.node.get("type"),
                    "slice": block.node.get("slice"),
                    "status": block.node.get("status"),
                    "depends-on": list(block.node.get("depends-on") or []),
                    "claims": list(block.node.get("claims") or []),
                    "claims-enabled": list(block.node.get("claims-enabled") or []),
                    "blocked-by": list(block.node.get("blocked-by") or []),
                }
                for item_id, block in self.items.items()
            },
            "claims": {
                claim_id: {
                    "label": block.node.get("label"),
                    "text": block.node.get("text"),
                    "locations": list(block.node.get("locations") or []),
                }
                for claim_id, block in self.claims.items()
            },
            "blockers": {
                blocker_id: {
                    "class": block.node.get("class"),
                    "resolution": block.node.get("resolution"),
                    "blocks": list(block.node.get("blocks") or []),
                }
                for blocker_id, block in self.blockers.items()
            },
            "defects": sorted(self.defects),
        }

    def slice_order(self):
        return sorted(self.slices, key=self._slice_key)

    @staticmethod
    def _slice_key(slice_id):
        match = re.fullmatch(r"S([0-9]+)", slice_id)
        return (int(match.group(1)) if match else 10**9, slice_id)

    @staticmethod
    def _item_key(item_id):
        match = re.fullmatch(r"WI-([0-9]+)", item_id)
        return (int(match.group(1)) if match else 10**9, item_id)

    def ordered_items(self, slice_id):
        """A slice's items in dependency order, ties broken by identifier.

        Deterministic by construction. The tie-break matters: without it two runs of the same
        plan could execute two independent items in either order, and a run that is not
        repeatable is not one anybody should point at their own code.
        """
        members = [
            item_id
            for item_id in (self.slices[slice_id].node.get("items") or [])
            if item_id in self.items
        ]
        remaining = sorted(members, key=self._item_key)
        placed = []
        seen = set()
        while remaining:
            ready = [
                item_id
                for item_id in remaining
                if all(
                    dependency in seen or dependency not in members
                    for dependency in (self.items[item_id].node.get("depends-on") or [])
                )
            ]
            if not ready:
                # A cycle. The linter reports it separately; here the remaining items are
                # appended in identifier order so the caller gets a complete list rather than
                # a silently truncated one.
                placed.extend(remaining)
                break
            placed.extend(ready)
            seen.update(ready)
            remaining = [item_id for item_id in remaining if item_id not in seen]
        return placed

    # ---- writing ---------------------------------------------------------------------

    def set_scalar(self, kind, block_id, key, value):
        """Rewrite one scalar value in place. Returns True when the file changed.

        This is the write that has to be surgical. It replaces exactly the lines the key's
        value occupies — ``value_spans`` gives that range — and touches nothing else, so every
        comment the owner wrote at review survives every status change of the run.

        The one comment it does not preserve is a trailing comment on the line it rewrites,
        which described the value being replaced.
        """
        if isinstance(value, (dict, list)):
            raise ValueError(
                f"set_scalar was given a {type(value).__name__} for {key!r}; use set_field, "
                "which renders structures"
            )
        return self.set_field(kind, block_id, key, value)

    def set_field(self, kind, block_id, key, value):
        """Rewrite a field in place, or append it to the block when it is not there yet.

        Appending happens at the end of the block body rather than at any chosen position.
        That is the only insertion point that is safe without re-serialising: a key inserted
        between two others could land inside a nested mapping that the line before it opened.
        """
        block = self.node(kind, block_id)
        node = block.node
        indent = self._block_indent(block)
        rendered = render_field(key, value, indent)

        lines = self.text.split("\n")

        if key in node:
            if self._unchanged(node, key, value):
                return False
            start, end = node.value_spans[key]
            new_lines = lines[: start - 1] + rendered + lines[end:]
        else:
            new_lines = lines[: block.end_line - 1] + rendered + lines[block.end_line - 1 :]

        return self._commit(
            "\n".join(new_lines), f"{kind} {block_id}: set `{key}`"
        )

    def _block_indent(self, block):
        """The column a block's top-level keys sit at, measured rather than assumed.

        It is zero in every plan this suite writes, because a fenced block starts at the
        margin. It is measured anyway: a field appended at the wrong column parses as part of
        whatever mapping preceded it, which is a corruption that still lints.
        """
        line = self.text.split("\n")[block.node.line - 1]
        return len(line) - len(line.lstrip(" "))

    def _unchanged(self, node, key, value):
        """Whether the field already holds this value, so the write is a no-op.

        Idempotence is a requirement rather than an optimisation: a run that resumes, or an
        executor that writes the same status twice, must not append a second copy of anything
        or churn the file. Trailing whitespace is normalised out of the comparison because a
        folded scalar reads back with the newline its chomping added.
        """
        current = node.get(key)
        if isinstance(current, str) and isinstance(value, str):
            return current.strip() == value.strip()
        return current == value

    def upsert_block(self, section, kind, fields, identity, intro=None):
        """Append a fenced block to a section, or replace the one that already matches.

        ``identity`` is the natural key — ``{"item": "WI-04", "attempt": 2}`` for a log entry,
        ``{"id": "DF-1"}`` for a defect, ``{}`` for the single run summary. Matching on it is
        what makes appending idempotent: re-running a slice rewrites its log entry rather than
        stacking a second one beside it.
        """
        existing = None
        for block in self.by_kind.get(kind, []):
            if all(block.node.get(k) == v for k, v in identity.items()):
                existing = block
                break

        body = render_block(kind, fields)
        lines = self.text.split("\n")

        if existing is not None:
            if self.text.split("\n")[existing.fence_line - 1 : existing.end_line] == body.split("\n"):
                return False
            new_lines = lines[: existing.fence_line - 1] + body.split("\n") + lines[existing.end_line :]
            return self._commit(
                "\n".join(new_lines), f"{kind} {identity}: replace in {section}"
            )

        insert_at = self._section_insert_point(lines, section)
        if insert_at is None:
            return self._commit(
                self._append_section(section, body, intro),
                f"{kind} {identity}: new section `{section}`",
            )
        new_lines = lines[:insert_at] + ["", *body.split("\n")] + lines[insert_at:]
        return self._commit("\n".join(new_lines), f"{kind} {identity}: append to {section}")

    def _section_insert_point(self, lines, title):
        """The line index at which a new block belongs in the named section, or None.

        The end of the section rather than the start, so blocks appear in the order they were
        written. Trailing blank lines and a trailing horizontal rule are stepped back over, so
        the rule stays between sections where the plan template puts it.
        """
        wanted = title.strip().lower()
        start = None
        for index, line in enumerate(lines):
            match = _HEADING_RE.match(line)
            if not match:
                continue
            if start is None and match.group(2).strip().lower() == wanted:
                start = index
                continue
            if start is not None:
                end = index
                break
        else:
            end = len(lines)
        if start is None:
            return None
        while end > start + 1 and (lines[end - 1].strip() == "" or lines[end - 1].strip() == "---"):
            end -= 1
        return end

    def _append_section(self, title, body, intro):
        number = 1
        for line in self.text.split("\n"):
            match = _HEADING_RE.match(line)
            if match and match.group(1):
                number = max(number, int(match.group(1)) + 1)
        parts = [self.text.rstrip("\n"), "", "---", "", f"## {number}. {title}", ""]
        if intro:
            parts += [intro.strip(), ""]
        parts += [body, ""]
        return "\n".join(parts)

    # ---- the gate --------------------------------------------------------------------

    @contextlib.contextmanager
    def transaction(self, description="a group of writes"):
        """Several writes checked as one, rolled back together if the group fails to lint.

        Every ordinary write is linted on its own, and that is right for stage three: the
        writeback order there is a consequence of the rules, and each intermediate state is
        one the linter accepts. Stage four has one pair of writes where no order works. A
        `requirement-wrong` decision must relabel its claim `ratified-as-observed` *and*
        record the close-out block that authorises the relabelling, and the linter checks both
        directions — a decision with an un-relabelled claim fails, and a relabelled claim with
        no decision behind it fails. Whichever is written first introduces the other's failure
        and is rolled back.

        The two rules are both worth having, so the writer grew the ability to make two writes
        one. Nothing is relaxed: the group is linted exactly as a single write would be, and a
        group that fails leaves the file byte-identical to how it started.
        """
        if not self.lint_writes:
            yield self
            return
        snapshot = self.text
        self.lint_writes = False
        try:
            yield self
        except Exception:
            self._write(snapshot)
            self.reload()
            raise
        finally:
            self.lint_writes = True

        introduced = sorted(self._problem_keys() - self.baseline)
        if introduced:
            problems = [
                problem
                for problem in self._lint()
                if (problem.rule, problem.message) in set(introduced)
            ]
            self._write(snapshot)
            self.reload()
            raise WriteRejected(description, problems)

    def _commit(self, new_text, description):
        old_text = self.text
        self._write(new_text)
        try:
            self.reload()
        except Exception:
            self._write(old_text)
            self.reload()
            raise

        if not self.lint_writes:
            return True

        introduced = sorted(self._problem_keys() - self.baseline)
        if introduced:
            problems = [
                problem
                for problem in self._lint()
                if (problem.rule, problem.message) in set(introduced)
            ]
            self._write(old_text)
            self.reload()
            raise WriteRejected(description, problems)
        return True

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.text = text

    def _lint(self):
        problems, _ = self._plan_lint.lint(self.path, self.assessment, self.phase)
        return problems

    def _problem_keys(self):
        return {(problem.rule, problem.message) for problem in self._lint()}


# --------------------------------------------------------------------------------------
# The bundled tests
# --------------------------------------------------------------------------------------
#
# This module is the piece whose failure silently corrupts the running record: a writer that
# drops a comment, or shifts a line, or appends a second copy of a block, produces a plan that
# still lints and no longer says what happened. So it carries its own tests rather than
# relying on the end-to-end run to notice.


SAMPLE = '''\
# A plan

Some prose the owner wrote.

```yaml work-item
id: WI-01
type: infrastructure
slice: S0
title: "Do the thing"
status: pending
notes: >
  A folded scalar that runs over more than one line so that the span logic has something
  with a real end line to replace.
```

<!-- a review comment the owner added -->

## 2. Another section

```yaml claim
id: C1
label: pinned
```

Trailing prose.
'''


def _selftest():
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  ok    {name}")
        else:
            failures.append(name)
            print(f"  FAIL  {name}{(': ' + detail) if detail else ''}")

    workdir = tempfile.mkdtemp(prefix="planio-selftest-")
    try:
        path = os.path.join(workdir, "plan.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE)
        original = SAMPLE

        # Linting is off for the sample, which is a fragment rather than a whole plan. The
        # gate itself is exercised end to end against a real plan; what is under test here is
        # the byte-exactness of the edits.
        plan = Plan(path, lint_writes=False)

        # 1. Round trip with no writes changes nothing.
        plan.reload()
        check("round trip is byte-identical", plan.text == original)

        # 2. A status rewrite mid-file touches exactly one line.
        changed = plan.set_field("work-item", "WI-01", "status", "in-progress")
        after = plan.text
        before_lines = original.split("\n")
        after_lines = after.split("\n")
        differing = [
            i for i in range(max(len(before_lines), len(after_lines)))
            if before_lines[i:i + 1] != after_lines[i:i + 1]
        ]
        check("status rewrite reports a change", changed)
        check("status rewrite touches one line", len(differing) == 1, str(differing))
        check(
            "the owner's comment survives",
            "<!-- a review comment the owner added -->" in after,
        )
        check("prose above survives", "Some prose the owner wrote." in after)
        check("prose below survives", after.rstrip().endswith("Trailing prose."))

        # 3. The same write again is a no-op.
        check("rewriting the same value changes nothing", plan.set_field(
            "work-item", "WI-01", "status", "in-progress") is False)
        check("and leaves the file untouched", plan.text == after)

        # 4. A folded scalar is replaced whole, not partly.
        plan.set_field("work-item", "WI-01", "notes", "One short note.")
        check("folded scalar collapses to one line", "notes: One short note." in plan.text)
        check(
            "the block still parses",
            plan.items["WI-01"].node.get("notes") == "One short note.",
        )

        # 5. A field that does not exist is appended inside its own block.
        plan.set_field("work-item", "WI-01", "commit", "abc1234")
        node = plan.items["WI-01"].node
        check("appended field parses back", node.get("commit") == "abc1234")
        check(
            "appended field landed inside the block",
            plan.items["WI-01"].fence_line < node.line_of("commit") < plan.items["WI-01"].end_line,
        )

        # 6. A structured field renders as block YAML and reads back equal.
        actuals = {
            "attempts": 2,
            "files_touched": {"production": [], "test": ["tests/test_a.py"], "config": []},
            "checks": [{"kind": "tests-pass", "outcome": "passed"}],
        }
        plan.set_field("work-item", "WI-01", "actuals", actuals)
        stored = planlib.to_plain(plan.items["WI-01"].node.get("actuals"))
        check("structured field round-trips", stored == actuals, repr(stored))

        # 7. Appending to a section that exists.
        plan.upsert_block(
            "Another section", "claim",
            {"id": "C2", "label": "pinned"}, {"id": "C2"},
        )
        check("appended block parses", "C2" in plan.claims)
        check(
            "it landed in the named section",
            plan.text.index("id: C2") > plan.text.index("## 2. Another section"),
        )

        # 8. Appending to a section that does not exist creates it, numbered next.
        plan.upsert_block(
            LOG_SECTION, "claim", {"id": "C3", "label": "pinned"}, {"id": "C3"},
            intro="Written by stage three.",
        )
        check("missing section is created", f"## 3. {LOG_SECTION}" in plan.text)
        check("its intro is written", "Written by stage three." in plan.text)
        check("and the block is in it", "C3" in plan.claims)

        # 9. Upserting the same identity replaces rather than duplicates.
        plan.upsert_block(
            LOG_SECTION, "claim", {"id": "C3", "label": "cited"}, {"id": "C3"},
        )
        check("upsert does not duplicate", plan.text.count("id: C3") == 1)
        check("upsert replaced the value", plan.claims["C3"].node.get("label") == "cited")

        # 10. An identical upsert is a no-op.
        check("identical upsert changes nothing", plan.upsert_block(
            LOG_SECTION, "claim", {"id": "C3", "label": "cited"}, {"id": "C3"}) is False)

        # 11. Everything outside the touched regions is still byte-identical.
        check(
            "untouched prose is unchanged",
            plan.text.split("```yaml work-item")[0] == original.split("```yaml work-item")[0],
        )

        # 12. A value needing quotes gets them, and reads back unquoted.
        plan.set_field("work-item", "WI-01", "title", "yes: a colon, and a leading word")
        check(
            "ambiguous scalar is quoted and round-trips",
            plan.items["WI-01"].node.get("title") == "yes: a colon, and a leading word",
        )

        # 13. A multi-line string uses a literal block, because folding would change it.
        plan.set_field("work-item", "WI-01", "notes", "line one\nline two")
        check(
            "multi-line string survives verbatim",
            plan.items["WI-01"].node.get("notes").rstrip("\n") == "line one\nline two",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("all planio self-tests passed")
    return 0


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan", nargs="?", help="path to the plan file")
    parser.add_argument("--assessment", help="assessment report, for the full lint")
    parser.add_argument("--phase", default="executed",
                        choices=("planned", "reviewed", "executed", "closed"))
    parser.add_argument("--show", action="store_true", help="print the run state as JSON")
    parser.add_argument("--set", nargs=3, metavar=("ITEM", "KEY", "VALUE"),
                        help="set one scalar field on one work item")
    parser.add_argument("--set-claim", nargs=3, metavar=("CLAIM", "KEY", "VALUE"),
                        help="set one scalar field on one claim, for the dispute path")
    parser.add_argument("--selftest", action="store_true", help="run the bundled tests")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()
    if not args.plan:
        parser.error("a plan path is required unless --selftest is given")

    plan = Plan(args.plan, args.assessment, args.phase)

    if plan.baseline:
        print(
            f"note: {len(plan.baseline)} pre-existing lint problem(s) in {args.plan}. Writes "
            "are checked against this baseline, so only problems a write introduces roll it "
            "back. Pre-flight refuses to start a run on a plan that does not lint, so this "
            "should not happen mid-run.",
            file=sys.stderr,
        )

    for option, kind in ((args.set, "work-item"), (args.set_claim, "claim")):
        if not option:
            continue
        block_id, key, raw = option
        try:
            changed = plan.set_scalar(kind, block_id, key, raw)
        except (PlanNotFound, WriteRejected) as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"{'wrote' if changed else 'unchanged'}: {block_id}.{key} = {raw}")
        return 0

    if args.show:
        print(json.dumps(plan.run_state(), indent=2, ensure_ascii=False))
        return 0

    state = plan.run_state()
    print(f"{args.plan} — {len(state['items'])} item(s) in {len(state['slices'])} slice(s)")
    print(f"  approved: {state['approved']}")
    for entry in state["slices"]:
        print(f"  {entry['id']}: " + ", ".join(
            f"{item} [{state['items'][item]['status']}]" for item in entry["items"]
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

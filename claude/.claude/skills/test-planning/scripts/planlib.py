#!/usr/bin/env python3
"""Shared machinery for reading and validating a test plan.

Three things live here, and every other script in this skill imports them:

1. **A strict YAML subset parser** that records the file line of every key. The line spans
   are not a nicety: stage three writes execution status back into the plan file, and it
   must be able to rewrite one ``status:`` line without disturbing the comments the owner
   added at review. A parser that returns only values cannot do that.

2. **A span-aware block extractor** that finds the fenced YAML blocks in the plan's
   Markdown and reports where each one starts, so every problem the linter reports names a
   real file and line.

3. **A declarative schema validator** and the concrete schemas for every block type.

**Why a bundled parser rather than PyYAML.** PyYAML is not in the standard library. Both
this stage and the assessment stage forbid installing anything into the target repository,
and the remedy for PyYAML's absence is exactly the ``pip install`` they forbid. A linter
that cannot run is a gate that has silently stopped holding, which is worse than no gate,
because the plan still says it was linted. Where PyYAML *is* importable this module uses it
as a cross-check — parsing the same text both ways and comparing — so the subset parser is
held to a real implementation's behavior rather than trusted on its own.

**The subset is deliberately small.** Block mappings, block sequences, block scalars,
quoted and plain scalars, comments, ``null``/``true``/``false``, integers and floats.
Anchors, aliases, tags, flow collections, multiple documents, and complex keys are all
errors with a message saying so. The plan is written by this skill and edited by a human;
none of those constructs earns its ambiguity.
"""

import re

# --------------------------------------------------------------------------------------
# Problems
# --------------------------------------------------------------------------------------


class Problem:
    """A single lint or parse failure, always carrying a file and a line."""

    __slots__ = ("rule", "path", "line", "message", "fix")

    def __init__(self, rule, path, line, message, fix=None):
        self.rule = rule
        self.path = path
        self.line = line
        self.message = message
        self.fix = fix

    def as_dict(self):
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "fix": self.fix,
        }

    def __str__(self):
        head = f"{self.path}:{self.line}: [{self.rule}] {self.message}"
        return head + (f"\n    fix: {self.fix}" if self.fix else "")


class PlanYamlError(Exception):
    """A parse failure in the YAML subset. Carries the absolute file line."""

    def __init__(self, line, message, fix=None):
        super().__init__(message)
        self.line = line
        self.message = message
        self.fix = fix


# --------------------------------------------------------------------------------------
# Nodes: plain data that also remembers where it came from
# --------------------------------------------------------------------------------------


class MapNode(dict):
    """A mapping that also records the file line of each key.

    It subclasses ``dict`` so that everything downstream — schema checks, comparisons
    against PyYAML's output, JSON serialisation — treats it as ordinary data.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line = 0
        self.end_line = 0
        self.key_lines = {}
        self.value_spans = {}

    def line_of(self, key, default=None):
        """The file line the given key sits on. What stage three writes status back with."""
        return self.key_lines.get(key, default if default is not None else self.line)


class SeqNode(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line = 0
        self.end_line = 0
        self.item_lines = []

    def line_of(self, index):
        if 0 <= index < len(self.item_lines):
            return self.item_lines[index]
        return self.line


def to_plain(value):
    """Strip the span information, leaving ordinary dicts and lists."""
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    return value


# --------------------------------------------------------------------------------------
# The YAML subset parser
# --------------------------------------------------------------------------------------

# A `key: value` line. The three alternatives are a double-quoted key, a single-quoted key,
# and a plain one.
#
# The plain alternative excludes a leading quote character, and that exclusion is the whole
# reason this comment exists. Without it, a line that is entirely one quoted scalar —
# `- "parseSpec returns useShell false for a shell: false line"` — fails the quoted-key
# alternative (there is no colon after the closing quote), falls through to the plain one,
# and gets split at the colon *inside* the string into a key and a value. The block then
# parses into something PyYAML disagrees with, which is how this was found: the
# cross-check of R-11.1 reported a disagreement on a real plan. A line beginning with a
# quote is a quoted scalar or a quoted key; it is never a plain key.
_KEY_RE = re.compile(r"""^(?P<key>"[^"]*"|'[^']*'|[^\s:#'"][^:#]*?)\s*:(?P<rest>\s.*|)$""")
_BLOCK_SCALAR_RE = re.compile(r"^(?P<style>[|>])(?P<chomp>[-+]?)(?P<indent>[0-9]*)\s*$")
_INT_RE = re.compile(r"^[-+]?[0-9][0-9_]*$")
_FLOAT_RE = re.compile(r"^[-+]?(?:[0-9]*\.[0-9]+|[0-9]+\.[0-9]*)(?:[eE][-+]?[0-9]+)?$")

# YAML 1.1 reads these as booleans and YAML 1.2 does not. Rather than pick a side and
# disagree with whichever parser the reader has, the subset rejects them and asks for
# quotes. This is the "Norway problem" and it is not worth inheriting.
_AMBIGUOUS_BOOLS = {"yes", "no", "on", "off", "y", "n", "Yes", "No", "On", "Off", "Y", "N",
                    "YES", "NO", "ON", "OFF", "True", "False", "TRUE", "FALSE", "Null", "NULL"}

# The same family of trap as the ambiguous booleans, and found the same way: PyYAML's implicit
# resolver turns an unquoted `2026-08-01T09:07:00Z` into a `datetime` object while this parser
# leaves it a string, so the R-11.1 cross-check reports a whole-block disagreement whose only
# real content is one unquoted scalar. Every date in this suite's plans is a string — nothing
# does arithmetic on one — so the subset requires the quotes that make it one.
_DATE_LIKE = re.compile(
    r"^\d{4}-\d{1,2}-\d{1,2}(?:[Tt ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*"
    r"(?:[Zz]|[+-]\d{1,2}(?::?\d{2})?)?)?$"
)

_FORBIDDEN_STARTS = {
    "&": "anchors",
    "*": "aliases",
    "!": "tags",
    "%": "directives",
    "?": "complex keys",
}


class _Reader:
    def __init__(self, lines, offset):
        self.lines = list(lines)
        self.i = 0
        self.offset = offset

    def lineno(self, index=None):
        return (self.i if index is None else index) + self.offset

    def _significant(self, index):
        """True when the line at ``index`` is neither blank nor a whole-line comment."""
        raw = self.lines[index]
        stripped = raw.strip()
        return bool(stripped) and not stripped.startswith("#")

    def peek(self):
        """Return (indent, content, lineno) for the next significant line, or None."""
        j = self.i
        while j < len(self.lines):
            if self._significant(j):
                raw = self.lines[j]
                leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
                if "\t" in leading:
                    raise PlanYamlError(
                        j + self.offset,
                        "tab character in indentation",
                        "Indent with spaces only. YAML forbids tabs in indentation, and a "
                        "tab that looks like alignment in one editor is a parse error in "
                        "every parser.",
                    )
                stripped = raw.lstrip(" ")
                indent = len(raw) - len(stripped)
                self.i = j
                return indent, stripped.rstrip(), j + self.offset
            j += 1
        self.i = len(self.lines)
        return None

    def advance(self):
        self.i += 1


def parse_yaml(text, first_line=1):
    """Parse the YAML subset. ``first_line`` is the file line of the text's first line."""
    reader = _Reader(text.split("\n"), first_line)
    head = reader.peek()
    if head is None:
        return None
    indent, content, lineno = head
    if content in ("---", "..."):
        raise PlanYamlError(
            lineno,
            "document markers are not part of this subset",
            "One block, one document. Remove the `---` or `...` line.",
        )
    value = _parse_block(reader, indent)
    leftover = reader.peek()
    if leftover is not None:
        raise PlanYamlError(
            leftover[2],
            f"unexpected content at indentation {leftover[0]} after the block ended",
            "Check the indentation; every key of a block sits at the same column.",
        )
    return value


def _parse_block(reader, indent):
    head = reader.peek()
    if head is None:
        return None
    _, content, _ = head
    if content == "-" or content.startswith("- "):
        return _parse_sequence(reader, indent)
    return _parse_mapping(reader, indent)


def _parse_mapping(reader, indent):
    node = MapNode()
    first = True
    last_line = None
    while True:
        head = reader.peek()
        if head is None:
            break
        line_indent, content, lineno = head
        if line_indent < indent:
            break
        if line_indent > indent:
            raise PlanYamlError(
                lineno,
                f"unexpected indentation: expected column {indent}, found {line_indent}",
                "Every key of a mapping sits at the same column as its siblings.",
            )
        if content.startswith("- "):
            if first:
                return _parse_sequence(reader, indent)
            break
        match = _KEY_RE.match(content)
        if not match:
            _reject_forbidden(content, lineno)
            raise PlanYamlError(
                lineno,
                f"expected `key: value`, found {content!r}",
                "Every line of a mapping is a key, a colon, and a value. "
                "Multi-line plain scalars are not part of this subset — use `|` or quotes.",
            )
        raw_key = match.group("key").strip()
        key = _unquote(raw_key, lineno)
        # The Norway problem applies to keys as well as values, and only the value half was
        # guarded. `on:` is a key to PyYAML's YAML 1.1 resolver only after it has become the
        # boolean `True`, so a mapping with an `on` field parses here as `{'on': ...}` and
        # there as `{True: ...}` — which the R-11.1 cross-check reports as a disagreement
        # rather than as the field-naming mistake it is. That is how this was found: an
        # `approved: {by, on, note}` block written into a fixture failed the cross-check with
        # a hundred-line diff whose only difference was one key.
        if raw_key[:1] not in "\"'" and raw_key in _AMBIGUOUS_BOOLS:
            raise PlanYamlError(
                lineno,
                f"{raw_key!r} is read as a field name by some YAML parsers and as a boolean "
                "by others, so it cannot be a key here",
                "Rename the field. `on`, `off`, `yes`, and `no` are the usual offenders; "
                "`date` in place of `on` reads better anyway. Quoting it would work and is "
                "worse, because the quotes are then load-bearing and the next person to "
                "tidy them up breaks the plan.",
            )
        if key in node:
            raise PlanYamlError(lineno, f"duplicate key {key!r} in the same mapping")
        rest = match.group("rest").strip()
        reader.advance()
        value, end_line = _parse_value(reader, rest, indent, lineno)
        node[key] = value
        node.key_lines[key] = lineno
        node.value_spans[key] = (lineno, end_line)
        last_line = end_line
        if first:
            node.line = lineno
            first = False
    node.end_line = last_line if last_line is not None else node.line
    return node


def _parse_sequence(reader, indent):
    node = SeqNode()
    first = True
    last_line = None
    while True:
        head = reader.peek()
        if head is None:
            break
        line_indent, content, lineno = head
        if line_indent != indent or not (content == "-" or content.startswith("- ")):
            break
        if first:
            node.line = lineno
            first = False

        raw = reader.lines[reader.i]
        dash_column = len(raw) - len(raw.lstrip(" "))
        after = content[1:]

        if after.strip() == "":
            reader.advance()
            value, end_line = _parse_value(reader, "", indent, lineno)
        else:
            item_offset = len(after) - len(after.lstrip(" "))
            item_column = dash_column + 1 + item_offset
            item_content = after.strip()
            if item_content.startswith("- "):
                raise PlanYamlError(
                    lineno,
                    "a sequence directly inside a sequence is not part of this subset",
                    "Give the inner sequence a key, or flatten it.",
                )
            if _KEY_RE.match(item_content):
                # `- key: value` starts a mapping whose column is where the key begins.
                # Rewrite the line so the mapping parser sees an ordinary first key.
                reader.lines[reader.i] = " " * item_column + item_content
                value = _parse_mapping(reader, item_column)
                end_line = value.end_line if isinstance(value, MapNode) else lineno
            else:
                reader.advance()
                value, end_line = _parse_value(reader, item_content, indent, lineno)
        node.append(value)
        node.item_lines.append(lineno)
        last_line = end_line
    node.end_line = last_line if last_line is not None else node.line
    return node


def _parse_value(reader, rest, parent_indent, lineno):
    """Parse the value that follows ``key:``. Returns (value, last_line)."""
    if rest == "":
        head = reader.peek()
        if head is None:
            return None, lineno
        child_indent, child_content, child_lineno = head
        is_sequence = child_content == "-" or child_content.startswith("- ")
        # A sequence may sit at its key's own column; a mapping may not.
        if child_indent > parent_indent or (is_sequence and child_indent == parent_indent):
            block = _parse_block(reader, child_indent)
            end = getattr(block, "end_line", child_lineno)
            return block, end
        return None, lineno

    _reject_forbidden(rest, lineno)

    block_scalar = _BLOCK_SCALAR_RE.match(rest)
    if block_scalar:
        return _parse_block_scalar(reader, block_scalar, parent_indent, lineno)

    if rest[0] in "[{":
        # The one flow construct the subset allows is an empty collection, because block
        # style has no way to write one and `depends-on:` with nothing after it parses as
        # null rather than as an empty list. Anything with content must be block style.
        bare = _strip_comment(rest).strip()
        if bare == "[]":
            empty = SeqNode()
            empty.line = empty.end_line = lineno
            return empty, lineno
        if bare == "{}":
            empty = MapNode()
            empty.line = empty.end_line = lineno
            return empty, lineno
        raise PlanYamlError(
            lineno,
            "flow collections are not part of this subset",
            "Write the list or mapping in block style, one item per line. Only the empty "
            "forms `[]` and `{}` are permitted, because block style cannot express them. "
            "Block style is what makes line-level editing and status writeback safe.",
        )
    return _parse_scalar(rest, lineno), lineno


def _reject_forbidden(text, lineno):
    if text and text[0] in _FORBIDDEN_STARTS:
        raise PlanYamlError(
            lineno,
            f"{_FORBIDDEN_STARTS[text[0]]} are not part of this subset",
            "Write the value out in full. The plan is read by people as well as scripts.",
        )


def _parse_block_scalar(reader, match, parent_indent, lineno):
    style = match.group("style")
    chomp = match.group("chomp")
    explicit_indent = match.group("indent")

    body = []
    block_indent = None
    if explicit_indent:
        block_indent = parent_indent + int(explicit_indent)

    # A text ending in a newline splits into a final empty element that is not a line.
    # Treating it as a blank content line adds a newline PyYAML does not produce.
    limit = len(reader.lines)
    if limit and reader.lines[-1] == "":
        limit -= 1

    while reader.i < limit:
        raw = reader.lines[reader.i]
        stripped = raw.strip()
        if stripped == "":
            body.append("")
            reader.advance()
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent <= parent_indent:
            break
        if block_indent is None:
            block_indent = indent
        if indent < block_indent:
            break
        body.append(raw[block_indent:])
        reader.advance()

    last_line = reader.lineno(reader.i - 1)

    # Whether the scalar's final line was followed by a line break in the source. A block
    # scalar that runs to the very end of a text with no trailing newline has none, and
    # clip chomping must not invent one — this is the only place the bundled parser and
    # PyYAML ever disagreed during development.
    consumed_to_end = reader.i >= len(reader.lines)
    ended_with_newline = (not consumed_to_end) or (bool(reader.lines) and reader.lines[-1] == "")

    trailing_blanks = 0
    while body and body[-1] == "":
        body.pop()
        trailing_blanks += 1

    if style == "|":
        text = "\n".join(body)
    else:
        text = _fold(body)

    if chomp == "-":
        pass  # strip: no trailing line break at all
    elif chomp == "+":
        if text and ended_with_newline:
            text += "\n"
        text += "\n" * trailing_blanks
    elif text and ended_with_newline:
        text += "\n"  # clip: exactly one

    return text, last_line


def _fold(body):
    """Fold a `>` block scalar the way YAML specifies.

    Three rules, and getting any of them wrong makes the bundled parser disagree with
    PyYAML on text the plan actually contains:

    * a line break between two ordinary lines folds to a single space;
    * a break next to a **more-indented** line is kept literally, which is how a folded
      scalar holds a code sample or a list without losing its shape;
    * a run of *n* blank lines becomes *n* newlines, not *n* + 1.
    """
    chunks = []
    i = 0
    while i < len(body):
        if body[i].strip() == "":
            count = 0
            while i < len(body) and body[i].strip() == "":
                count += 1
                i += 1
            chunks.append(("breaks", count))
        else:
            chunks.append(("text", body[i]))
            i += 1

    out = []
    previous = None
    pending = 0
    for kind, value in chunks:
        if kind == "breaks":
            pending = value
            continue
        if previous is not None:
            if pending:
                out.append("\n" * pending)
            elif value.startswith(" ") or previous.startswith(" "):
                out.append("\n")
            else:
                out.append(" ")
        elif pending:
            out.append("\n" * pending)
        out.append(value)
        previous = value
        pending = 0
    return "".join(out)


def _strip_comment(text):
    """Remove a trailing ``# comment`` from a plain scalar, respecting quotes."""
    in_single = in_double = False
    for i, char in enumerate(text):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if i == 0 or text[i - 1] in " \t":
                return text[:i].rstrip()
    return text


def _unquote(text, lineno):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        if text[0] == "'":
            return text[1:-1].replace("''", "'")
        return _unescape_double(text[1:-1], lineno)
    return text


def _unescape_double(text, lineno):
    out = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            if i + 1 >= len(text):
                raise PlanYamlError(lineno, "string ends with a lone backslash")
            nxt = text[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            if nxt == "u" and i + 5 < len(text) + 1:
                try:
                    out.append(chr(int(text[i + 2 : i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            raise PlanYamlError(lineno, f"unsupported escape sequence \\{nxt}")
        out.append(char)
        i += 1
    return "".join(out)


def _parse_scalar(text, lineno):
    if text and text[0] in "\"'":
        closing = text[0]
        end = _find_closing_quote(text, closing, lineno)
        value = _unquote(text[: end + 1], lineno)
        trailer = text[end + 1 :].strip()
        if trailer and not trailer.startswith("#"):
            raise PlanYamlError(
                lineno, f"unexpected text after a quoted string: {trailer!r}"
            )
        return value

    text = _strip_comment(text).strip()
    if text == "" or text in ("null", "~"):
        return None
    if text in _AMBIGUOUS_BOOLS:
        raise PlanYamlError(
            lineno,
            f"{text!r} is read as a boolean by some YAML parsers and as a string by others",
            "Quote it, or write `true` / `false` / `null` in lower case.",
        )
    if _DATE_LIKE.match(text):
        raise PlanYamlError(
            lineno,
            f"{text!r} is read as a date by some YAML parsers and as a string by others",
            "Quote it: `\"" + text + "\"`. Nothing in a plan does arithmetic on a date, and "
            "an unquoted one turns into a datetime object in PyYAML and stays a string here — "
            "which the R-11.1 cross-check reports as a whole-block disagreement whose only "
            "real content is this one scalar.",
        )
    if text == "true":
        return True
    if text == "false":
        return False
    if _INT_RE.match(text):
        return int(text.replace("_", ""))
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _find_closing_quote(text, quote, lineno):
    i = 1
    while i < len(text):
        if text[i] == quote:
            if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            return i
        if quote == '"' and text[i] == "\\":
            i += 2
            continue
        i += 1
    raise PlanYamlError(
        lineno,
        "unterminated quoted string",
        "This subset does not support a scalar spanning several lines. Use `|` for that.",
    )


# --------------------------------------------------------------------------------------
# PyYAML cross-check
# --------------------------------------------------------------------------------------


def cross_check_with_pyyaml(text, parsed):
    """Compare this parser's result with PyYAML's, when PyYAML is importable.

    Returns (checked, message). ``checked`` is False when PyYAML is absent, which is not a
    failure — it is the situation this parser exists for. A mismatch when PyYAML *is*
    present is a real defect and the caller should surface it.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return False, "PyYAML is not installed; the bundled parser ran unchecked"

    try:
        reference = yaml.safe_load(text)
    except Exception as error:  # noqa: BLE001 - any parse failure is worth reporting
        return True, f"PyYAML rejected text this parser accepted: {error}"

    if to_plain(parsed) != reference:
        return True, (
            "the bundled parser and PyYAML disagree about this block. "
            f"bundled={to_plain(parsed)!r} pyyaml={reference!r}"
        )
    return True, None


# --------------------------------------------------------------------------------------
# Markdown block extraction
# --------------------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")


class Block:
    """One fenced block in the plan, with the file lines it occupies."""

    __slots__ = ("info", "kind", "fence_line", "end_line", "body", "body_start_line", "node")

    def __init__(self, info, kind, fence_line, end_line, body, body_start_line):
        self.info = info
        self.kind = kind
        self.fence_line = fence_line
        self.end_line = end_line
        self.body = body
        self.body_start_line = body_start_line
        self.node = None

    def __repr__(self):
        return f"<Block {self.kind!r} at line {self.fence_line}>"


def extract_blocks(text):
    """Every fenced block in the document, in order.

    A block whose info string is ``yaml <kind>`` gets that kind; anything else gets
    ``kind = None`` and is ignored by the linter. Nesting is handled by fence length, so a
    four-backtick fence may contain three-backtick fences — which the plan template uses
    when it shows an example of a block.
    """
    lines = text.split("\n")
    blocks = []
    fence_char = None
    fence_len = 0
    info = None
    start = 0
    body = []

    for number, line in enumerate(lines, start=1):
        match = _FENCE_RE.match(line)
        if fence_char is None:
            if match:
                fence_char = match.group(2)[0]
                fence_len = len(match.group(2))
                info = match.group(3).strip()
                start = number
                body = []
            continue
        if (
            match
            and match.group(2)[0] == fence_char
            and len(match.group(2)) >= fence_len
            and match.group(3).strip() == ""
        ):
            kind = None
            parts = info.split()
            if parts and parts[0] == "yaml" and len(parts) > 1:
                kind = parts[1]
            blocks.append(Block(info, kind, start, number, "\n".join(body), start + 1))
            fence_char = None
            info = None
            body = []
            continue
        body.append(line)

    if fence_char is not None:
        blocks.append(
            Block(info, None, start, len(lines), "\n".join(body), start + 1)
        )
    return blocks


def parse_blocks(text, path, problems):
    """Extract, parse, and attach nodes to every ``yaml <kind>`` block.

    Blocks that fail to parse are dropped after a problem is recorded, so one broken block
    does not hide every other rule's findings.
    """
    parsed = []
    for block in extract_blocks(text):
        if block.kind is None:
            continue
        try:
            block.node = parse_yaml(block.body, first_line=block.body_start_line)
        except PlanYamlError as error:
            problems.append(
                Problem("yaml-syntax", path, error.line, error.message, error.fix)
            )
            continue
        if block.node is None:
            problems.append(
                Problem(
                    "empty-block",
                    path,
                    block.fence_line,
                    f"the `{block.kind}` block is empty",
                )
            )
            continue
        if not isinstance(block.node, MapNode):
            problems.append(
                Problem(
                    "block-shape",
                    path,
                    block.fence_line,
                    f"a `{block.kind}` block must be a mapping, not a "
                    f"{type(block.node).__name__.replace('Node', '').lower()}",
                )
            )
            continue
        checked, message = cross_check_with_pyyaml(block.body, block.node)
        if checked and message:
            problems.append(
                Problem("parser-disagreement", path, block.fence_line, message)
            )
            continue
        parsed.append(block)
    return parsed


# --------------------------------------------------------------------------------------
# Declarative schema validation
# --------------------------------------------------------------------------------------


def _type_name(value):
    return {
        bool: "true/false",
        int: "an integer",
        float: "a number",
        str: "a string",
        type(None): "null",
    }.get(type(value), "a list" if isinstance(value, list) else "a mapping")


def _check_field(value, spec, path, line, problems, where):
    kind = spec["type"]

    if value is None:
        if spec.get("nullable"):
            return
        problems.append(
            Problem("field-type", path, line, f"{where} must not be null")
        )
        return

    if kind == "string":
        if not isinstance(value, str):
            problems.append(
                Problem("field-type", path, line, f"{where} must be a string, got {_type_name(value)}")
            )
            return
        if not value.strip():
            problems.append(Problem("field-empty", path, line, f"{where} must not be empty"))
            return
        if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
            problems.append(
                Problem(
                    "field-pattern",
                    path,
                    line,
                    f"{where} must match {spec['pattern']}, got {value!r}",
                    spec.get("fix"),
                )
            )
        if "enum" in spec and value not in spec["enum"]:
            problems.append(
                Problem(
                    "field-enum",
                    path,
                    line,
                    f"{where} must be one of {sorted(spec['enum'])}, got {value!r}",
                    spec.get("fix"),
                )
            )
        if spec.get("min_length") and len(value.strip()) < spec["min_length"]:
            problems.append(
                Problem(
                    "field-too-short",
                    path,
                    line,
                    f"{where} is {len(value.strip())} characters; at least "
                    f"{spec['min_length']} are required for it to say anything",
                    spec.get("fix"),
                )
            )
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(
                Problem("field-type", path, line, f"{where} must be an integer, got {_type_name(value)}")
            )
            return
        if "min" in spec and value < spec["min"]:
            problems.append(
                Problem("field-range", path, line, f"{where} must be at least {spec['min']}")
            )
    elif kind == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(
                Problem("field-type", path, line, f"{where} must be a number, got {_type_name(value)}")
            )
            return
        if "min" in spec and value < spec["min"]:
            problems.append(
                Problem("field-range", path, line, f"{where} must be at least {spec['min']}")
            )
        if "max" in spec and value > spec["max"]:
            problems.append(
                Problem("field-range", path, line, f"{where} must be at most {spec['max']}")
            )
    elif kind == "boolean":
        if not isinstance(value, bool):
            problems.append(
                Problem("field-type", path, line, f"{where} must be true or false, got {_type_name(value)}")
            )
    elif kind == "list":
        if not isinstance(value, list):
            problems.append(
                Problem(
                    "field-type",
                    path,
                    line,
                    f"{where} must be a list, got {_type_name(value)}",
                    "Write it in block style, one `- item` per line.",
                )
            )
            return
        if spec.get("min_items") and len(value) < spec["min_items"]:
            problems.append(
                Problem(
                    "field-too-few",
                    path,
                    line,
                    f"{where} needs at least {spec['min_items']} item(s), has {len(value)}",
                    spec.get("fix"),
                )
            )
        item_spec = spec.get("items")
        if item_spec:
            for i, item in enumerate(value):
                item_line = value.line_of(i) if isinstance(value, SeqNode) else line
                _check_field(item, item_spec, path, item_line, problems, f"{where}[{i}]")
    elif kind == "mapping":
        if not isinstance(value, dict):
            problems.append(
                Problem("field-type", path, line, f"{where} must be a mapping, got {_type_name(value)}")
            )
            return
        if "schema" in spec:
            validate_mapping(value, spec["schema"], path, problems, where, line)


def validate_mapping(node, schema, path, problems, where, fallback_line):
    """Validate one mapping against a schema of ``{name: spec}`` plus control keys.

    Control keys in the schema: ``_required`` (list of field names) and ``_allow_extra``.
    """
    required = schema.get("_required", [])
    allow_extra = schema.get("_allow_extra", False)
    fields = {k: v for k, v in schema.items() if not k.startswith("_")}

    line_of = node.line_of if isinstance(node, MapNode) else (lambda key, default=None: fallback_line)

    for name in required:
        if name not in node:
            problems.append(
                Problem(
                    "field-missing",
                    path,
                    fallback_line if not isinstance(node, MapNode) else node.line,
                    f"{where} is missing required field `{name}`",
                    fields.get(name, {}).get("fix"),
                )
            )

    for name, value in node.items():
        spec = fields.get(name)
        if spec is None:
            if not allow_extra:
                problems.append(
                    Problem(
                        "field-unknown",
                        path,
                        line_of(name, fallback_line),
                        f"{where} has an unrecognised field `{name}`",
                        "Check the spelling against references/work-item-schema.md. "
                        "Unrecognised fields are rejected because a misspelled field is "
                        "silently ignored otherwise.",
                    )
                )
            continue
        _check_field(
            value, spec, path, line_of(name, fallback_line), problems, f"{where}.{name}"
        )


# --------------------------------------------------------------------------------------
# The concrete plan schemas
# --------------------------------------------------------------------------------------

ITEM_ID = r"WI-[0-9]{2,}"
SLICE_ID = r"S[0-9]+"
CLAIM_ID = r"C[0-9]+"
ESCALATION_ID = r"E[0-9]+"
DECISION_ID = r"DEC-[0-9]+"
FLAGGED_ID = r"FLAG-[0-9]+"
BACKLOG_ID = r"BL-[0-9]+"
DEFECT_ID = r"DF-[0-9]+"
ASSESSMENT_ID = r"[FRXDQ][0-9]+"
BLOCKER_ID = rf"(?:{ESCALATION_ID}|{DECISION_ID})"

# Stage four's three identifier spaces, following the same discipline as everything above.
# `CO` numbers a close-out record, `DA` a document-amendment flag, and `PF` a pipeline
# finding. The last two outlive the run: they are written into the run ledger and retired
# only explicitly, so a number that has been issued is never reused for something else.
CLOSEOUT_ID = r"CO-[0-9]+"
AMENDMENT_ID = r"DA-[0-9]+"
FINDING_ID = r"PF-[0-9]{2,}"

ITEM_TYPES = {"infrastructure", "characterization", "seam", "unit-tests", "test-repair"}

# Statuses the execution stage writes and the planner never does. They live in this schema
# rather than the executor's because the plan file is the running record the stage four
# report is built from: a status the linter rejects is a status the executor cannot write.
# The phase gate in plan_lint.py refuses all of them outside `--phase executed`.
EXECUTION_STATUSES = {"done-with-defect", "blocked-by-failure", "stale"}

STATUSES = {
    "pending",
    "blocked-on-decision",
    "in-progress",
    "done",
    "skipped",
    "failed",
} | EXECUTION_STATUSES

# Claim labels, phase-gated. `cited` and `pinned` are what a planner may write; `ratified`
# arrives at the review sitting; the last two are execution-stage and close-out writes.
#
# `disputed` marks a pinned claim whose faithful test failed, which impeaches the planner's
# reading of the code rather than the code. `ratified-as-observed` marks a cited or ratified
# claim the owner ruled wrong at close-out, accepting the observed behavior instead.
#
# **`ratified-as-observed` belongs to the close-out phase and not to execution**, and the two
# used to share one bucket. Nothing in stage three may write it: R-2.5 of the execution
# document reserves the whole family of "the requirement was wrong" answers to the owner, and
# a label the executor could write is an answer the executor could give itself. It is the
# reason `closed` exists as a fourth phase rather than as a relaxation of the third.
PLANNED_CLAIM_LABELS = {"cited", "pinned"}
REVIEW_CLAIM_LABELS = {"ratified"}
EXECUTION_CLAIM_LABELS = {"disputed"}
CLOSEOUT_CLAIM_LABELS = {"ratified-as-observed"}

CLAIM_LABELS = (
    PLANNED_CLAIM_LABELS | REVIEW_CLAIM_LABELS | EXECUTION_CLAIM_LABELS | CLOSEOUT_CLAIM_LABELS
)

# What each phase may contain, cumulatively. A fresh plan carrying a `disputed` claim is
# asserting that execution found something before execution happened.
CLAIM_LABELS_BY_PHASE = {
    "planned": PLANNED_CLAIM_LABELS,
    "reviewed": PLANNED_CLAIM_LABELS | REVIEW_CLAIM_LABELS,
    "executed": PLANNED_CLAIM_LABELS | REVIEW_CLAIM_LABELS | EXECUTION_CLAIM_LABELS,
    "closed": CLAIM_LABELS,
}

# R-6.2's four close-out answers. Two of them change the branch and two deliberately do not.
#
# `fix-the-code`  — the defect is real and the code is wrong. Nothing is applied now; the red
#                   test stands as the ready-made verification and every later run re-reports
#                   the defect until it goes green.
# `requirement-wrong` — the claim was wrong and the observed behavior is accepted. The test is
#                   rewritten to assert what the code does, the claim is relabelled
#                   `ratified-as-observed`, and the source document is flagged for amendment.
# `accept-with-red` — the defect is real, the branch merges anyway, and continuous integration
#                   carries the enforcement. Nothing is applied.
# `downgrade`     — a known-failure marker is applied so the suite reports green. **Available
#                   only as the owner's recorded decision**, never by default and never to an
#                   agent, which is why it carries the strictest record of the four.
#
# They sit here rather than beside the close-out schema because the defect registry's
# `resolution` field is the same closed set, and the registry is defined further up.
CLOSEOUT_OPTIONS = {"fix-the-code", "requirement-wrong", "accept-with-red", "downgrade"}

# The options that apply a transformation to the branch, and therefore produce a commit.
CONSEQUENTIAL_OPTIONS = {"requirement-wrong", "downgrade"}

# What each option leaves the defect's test in. Declared rather than inferred, so the check
# runner has something to verify against and the linter has something to hold the option to.
RED_TEST_STATES = {"standing", "rewritten", "marked"}

RISK_TIERS = {"top", "high", "medium", "low"}
EFFORT_UNITS = {"hours", "sessions"}
CHECK_KINDS = {
    "file-exists",
    "tests-pass",
    "guard-holds",
    "mutation",
    "pattern-count",
}
COVERAGE_METRICS = {"lines", "branches", "functions", "statements"}

TARGET_SCHEMA = {
    "_required": ["file"],
    "file": {"type": "string"},
    "functions": {"type": "list", "items": {"type": "string"}},
    "lines": {"type": "string"},
    "note": {"type": "string"},
}

# `coverage-delta` is a field on the work item and **not** a completion check kind, even
# though it functions as one. It was both for a while, and the two copies drifted within a
# single writing session: four items declared a delta for two files and wrote the check for
# only one. R-7.1 already frames the field as a completion check rather than a goal, so the
# field is the single source and every entry is an implied check.
COVERAGE_DELTA_SCHEMA = {
    "_required": ["file", "metric", "from", "to", "baseline-source"],
    "file": {"type": "string"},
    "metric": {"type": "string", "enum": COVERAGE_METRICS},
    "from": {"type": "number", "min": 0, "max": 100},
    "to": {"type": "number", "min": 0, "max": 100},
    "baseline-source": {
        "type": "string",
        "enum": {"assessment-index", "slice-zero", "none"},
        "fix": "`assessment-index` when the assessment recorded this file's figure and that "
               "record is complete; `slice-zero` when the baseline only exists after slice "
               "zero runs, which is the usual answer because slice zero precedes every other "
               "item; `none` only for a file that does not exist at slice zero and is created "
               "by this plan, where zero really is true by construction.",
    },
    "note": {"type": "string"},
}

CHECK_SCHEMA = {
    "_required": ["kind"],
    "_allow_extra": True,
    "kind": {
        "type": "string",
        "enum": CHECK_KINDS,
        "fix": "The catalog is closed. See references/schema/completion-checks.md. "
               "`coverage-delta` is not in it: it is a field on the work item, and every "
               "entry there is already an implied completion check.",
    },
}

# Per-kind field requirements. These are what make "machine-checkable as written" a rule a
# script can enforce rather than a hope: a check missing the field an executor would need
# to run it is not machine-checkable, whatever its prose says.
CHECK_KIND_SCHEMAS = {
    "file-exists": {
        "_required": ["kind", "path"],
        "kind": {"type": "string"},
        "path": {"type": "string"},
        "absent": {"type": "boolean"},
    },
    "tests-pass": {
        "_required": ["kind", "command", "expect"],
        "kind": {"type": "string"},
        "command": {"type": "string", "min_length": 5},
        "tests": {"type": "list", "items": {"type": "string"}},
        "expect": {"type": "string", "enum": {"all-pass", "named-tests-fail"}},
    },
    "guard-holds": {
        "_required": ["kind", "item", "command"],
        "kind": {"type": "string"},
        "item": {"type": "string", "pattern": ITEM_ID},
        "command": {"type": "string", "min_length": 5},
    },
    "mutation": {
        "_required": [
            "kind",
            "claim",
            "file",
            "mutation",
            "command",
            "expect",
            "tests",
            "restore",
        ],
        "kind": {"type": "string"},
        # Which claim this mutation falsifies. Required, because the one-mutation-per-claim
        # rule of R-7.1 is otherwise unenforceable however carefully the check is written:
        # a linter looking at an item with a dozen claims and one mutation check cannot tell
        # whether that check covers the claim it was written for or a different one. The
        # per-item rule this replaced was satisfied by exactly that arrangement.
        "claim": {
            "type": "string",
            "pattern": CLAIM_ID,
            "fix": "Name the claim this edit falsifies, as `C7`. One mutation check "
                   "verifies one claim; an item asserting several carries several checks.",
        },
        "file": {"type": "string"},
        "mutation": {
            "type": "string",
            "min_length": 20,
            "fix": "State the edit precisely enough that two people would make the same one.",
        },
        "command": {"type": "string", "min_length": 5},
        "expect": {"type": "string", "enum": {"named-tests-fail"}},
        "tests": {
            "type": "list",
            "items": {"type": "string"},
            "min_items": 1,
            "fix": "A mutation that makes some test fail somewhere proves less than one "
                   "that makes the intended test fail. Name them.",
        },
        "restore": {"type": "string", "min_length": 5},
    },
    "pattern-count": {
        "_required": ["kind", "scope", "pattern", "expect"],
        "kind": {"type": "string"},
        "scope": {"type": "list", "items": {"type": "string"}, "min_items": 1},
        "pattern": {"type": "string"},
        "expect": {"type": "integer", "min": 0},
        "comparison": {"type": "string", "enum": {"exactly", "at-least", "at-most"}},
    },
}


def validate_check(check, path, line, problems, where):
    """Validate one completion check against its kind's field requirements."""
    if not isinstance(check, dict):
        problems.append(Problem("field-type", path, line, f"{where} must be a mapping"))
        return
    kind = check.get("kind")
    schema = CHECK_KIND_SCHEMAS.get(kind)
    if schema is None:
        return  # the generic schema already reported the bad or missing kind
    validate_mapping(check, schema, path, problems, f"{where} ({kind})", line)

    if kind == "pattern-count":
        pattern = check.get("pattern")
        if isinstance(pattern, str):
            try:
                re.compile(pattern)
            except re.error as error:
                problems.append(
                    Problem(
                        "check-bad-pattern",
                        path,
                        line,
                        f"{where}: `pattern` is not a valid regular expression: {error}",
                    )
                )
    for field in ("command", "restore"):
        value = check.get(field)
        if isinstance(value, str) and re.search(r"(?:^|\s)/(?:Users|home)/", value):
            problems.append(
                Problem(
                    "absolute-path",
                    path,
                    line,
                    f"{where}: `{field}` contains an absolute path, so nobody else and no "
                    "other checkout can run it",
                    "Use repository-relative paths and run from the repository root.",
                )
            )

# The escape valve for the mutation obligation (R-7.1). A claim that genuinely admits no
# small named falsifying edit is recorded here with the reason, rather than being given a
# check that does not falsify it or being dropped from the plan. Both of those are worse
# than a reviewable admission.
#
# The reason's length floor is doing real work. "N/A", "hard", and "not applicable" are the
# shapes a waiver takes when it is being used to get past the linter, and none of them
# survives forty characters. The standard is the same one the guard waiver is held to: a
# waiver whose reason is convenience rather than impossibility is a violation.
MUTATION_WAIVER_SCHEMA = {
    "_required": ["claim", "reason"],
    "claim": {"type": "string", "pattern": CLAIM_ID},
    "reason": {
        "type": "string",
        "min_length": 40,
        "fix": "State why this specific claim admits no small named edit that would falsify "
               "it. Convenience is not a reason; the owner reads these at the gate.",
    },
}

FOOTPRINT_SCHEMA = {
    "_required": ["production", "test", "config"],
    "production": {"type": "list", "items": {"type": "string"}},
    "test": {"type": "list", "items": {"type": "string"}},
    "config": {"type": "list", "items": {"type": "string"}},
}

EFFORT_SCHEMA = {
    "_required": ["unit", "value"],
    "unit": {
        "type": "string",
        "enum": EFFORT_UNITS,
        "fix": "An effort estimate without a unit cannot be checked against the "
               "single-session sizing rule in R-8.4.",
    },
    "value": {"type": "number", "min": 0},
}

# --------------------------------------------------------------------------------------
# What the execution stage writes
# --------------------------------------------------------------------------------------
#
# These shapes live in the planner's schema for the same reason the execution statuses do:
# the plan file is the running record the stage four report is built from, and stage three's
# own entry gate (its R-4.2) is this linter. A field the linter rejects is a field the
# executor cannot write, so an `actuals:` mapping with no schema here is not "undefined" — it
# is a `field-unknown` failure that would make the writeback impossible.
#
# **The planner never writes any of them.** The phase gate in plan_lint.py refuses every one
# outside `--phase executed`, exactly as it refuses the execution statuses and claim labels.

# The check kinds the runner reports on. Three of them are not entries in the closed catalog
# of authored checks, because nothing authors them: a `coverage-delta` entry on the item is an
# implied check, the claim-annotation check of R-5.7 is generated from the item's `claims`
# list, and the standing invariant of R-5.4 runs on every item whether it asks for it or not.
IMPLIED_CHECK_KINDS = {"coverage-delta", "claim-annotations", "standing-invariant"}
RUNNER_CHECK_KINDS = CHECK_KINDS | IMPLIED_CHECK_KINDS

# `suspended` is R-7.4: a mutation check against a claim whose test is already standing red in
# the defect registry proves nothing, so it is recorded as suspended rather than as passed.
# `not-run` is R-10.2: a check the runner could not execute is reported, never inferred.
CHECK_OUTCOMES = {"passed", "failed", "suspended", "not-run"}

RECORDED_CHECK_SCHEMA = {
    "_required": ["kind", "outcome"],
    "kind": {"type": "string", "enum": RUNNER_CHECK_KINDS},
    "outcome": {"type": "string", "enum": CHECK_OUTCOMES},
    "claim": {"type": "string", "pattern": CLAIM_ID},
    "detail": {
        "type": "string",
        "fix": "Required for any outcome other than `passed`. R-10.2 forbids inferring a "
               "check: an outcome with no detail is indistinguishable from a guess.",
    },
    "log": {"type": "string", "fix": "Sidecar path holding the full output (R-9.2)."},
}

ACTUALS_SCHEMA = {
    "_required": ["files_touched", "checks", "attempts"],
    "files_touched": {
        "type": "mapping",
        "schema": FOOTPRINT_SCHEMA,
        "fix": "Measured from the git diff of the item's commit, never self-reported "
               "(R-9.1). The underscore distinguishes it from the declared `files-touched`; "
               "the whole point of recording it is that the two can differ.",
    },
    "checks": {
        "type": "list",
        "items": {"type": "mapping", "schema": RECORDED_CHECK_SCHEMA},
        "min_items": 1,
    },
    "started": {"type": "string"},
    "finished": {"type": "string"},
    "attempts": {"type": "integer", "min": 1},
}

# One attempt at one item. Several blocks per item is the normal case for anything that took
# more than one try, and the retry history is what R-6.1's diagnosis is written from.
ATTEMPT_OUTCOMES = {"passed", "checks-failed", "reverted", "abandoned", "not-run"}

VERIFIER_VERDICTS = {"faithful", "unfaithful", "discriminating", "weak"}

VERIFIER_RECORD_SCHEMA = {
    "_required": ["brief", "verdict", "note"],
    "brief": {
        "type": "string",
        "enum": {"faithfulness", "slice-verification"},
        "fix": "`faithfulness` is R-7.3's mandatory per-red-test check; "
               "`slice-verification` is R-8.3's per-slice judgment pass.",
    },
    "verdict": {"type": "string", "enum": VERIFIER_VERDICTS},
    "note": {"type": "string", "min_length": 20},
    # `date` rather than `on`. A bare `on:` key is the boolean `True` to PyYAML's YAML 1.1
    # resolver, so the field would fail the R-11.1 cross-check on every plan that used it.
    "date": {"type": "string"},
}

EXECUTION_LOG_SCHEMA = {
    "_required": ["item", "attempt", "outcome", "summary"],
    "item": {"type": "string", "pattern": ITEM_ID},
    "attempt": {"type": "integer", "min": 1},
    "outcome": {"type": "string", "enum": ATTEMPT_OUTCOMES},
    "summary": {
        "type": "string",
        "min_length": 20,
        "fix": "What was attempted and what the check runner reported. R-10.2: state what is "
               "known and what is guessed, separately.",
    },
    "started": {"type": "string"},
    "finished": {"type": "string"},
    "checks": {"type": "list", "items": {"type": "mapping", "schema": RECORDED_CHECK_SCHEMA}},
    "verifier": {"type": "list", "items": {"type": "mapping", "schema": VERIFIER_RECORD_SCHEMA}},
    "log": {"type": "string"},
    "preserved-diff": {
        "type": "string",
        "fix": "The side branch holding a reverted seam's failing diff (R-6.3) or a dispute's "
               "evidence (R-7.5). Named here so the report can point at it.",
    },
    "note": {"type": "string"},
}

# R-7.2's registry. A defect is the code contradicting a claim the owner or a document made
# binding, and its committed red test is the enforcement mechanism.
DEFECT_SCHEMA = {
    "_required": ["id", "claim", "item", "observed", "test", "verification"],
    "id": {"type": "string", "pattern": DEFECT_ID},
    "claim": {"type": "string", "pattern": CLAIM_ID},
    "item": {"type": "string", "pattern": ITEM_ID},
    "observed": {
        "type": "string",
        "min_length": 20,
        "fix": "What the code actually does, stated so the owner can decide without running "
               "anything.",
    },
    "test": {"type": "mapping", "schema": {
        "_required": ["file", "name"],
        "file": {"type": "string"},
        "name": {"type": "string"},
    }},
    "verification": {
        "type": "mapping",
        "schema": VERIFIER_RECORD_SCHEMA,
        "fix": "R-7.3: no red test stands without a fresh-context verifier confirming the "
               "test asserts the claim. A deploy-blocking red raised over a misreading is the "
               "worst false alarm this stage can produce.",
    },
    "commit": {"type": "string"},
    "suspended-mutations": {
        "type": "list",
        "items": {"type": "string", "pattern": CLAIM_ID},
        "fix": "R-7.4: mutation checks against this registry test are suspended, never "
               "passed. List the claims whose checks are waiting for it to go green.",
    },
    "resolution": {
        "type": "string",
        "nullable": True,
        "enum": CLOSEOUT_OPTIONS,
        "fix": "R-7.6: the owner's close-out answer, one of `fix-the-code`, "
               "`requirement-wrong`, `accept-with-red`, or `downgrade`. Written at stage "
               "four, not by the executor — an executor that answers this has downgraded its "
               "own finding. It stays null through the executed phase and must be non-null at "
               "the closed one.",
    },
    "note": {"type": "string"},
}

# R-9.3's forward interface onto stage four: everything the report needs without re-parsing
# the plan. Written by scripts/run_summary.py in the execution skill, which derives every
# figure from the plan and the repository rather than from anything remembered.
RUN_SUMMARY_SCHEMA = {
    "_required": [
        "summary_version",
        "branch",
        "items",
        "claims",
        "defects",
        "disputes",
        "coverage",
        "footprint",
        "inherited_failures",
        "narrowings",
    ],
    "summary_version": {"type": "string", "enum": {"1.0"}},
    "branch": {"type": "string"},
    "base_commit": {"type": "string", "nullable": True},
    "started": {"type": "string"},
    "finished": {"type": "string"},
    "items": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["status", "count", "ids"],
        "status": {"type": "string", "enum": STATUSES},
        "count": {"type": "integer", "min": 0},
        "ids": {"type": "list", "items": {"type": "string", "pattern": ITEM_ID}},
    }}},
    "claims": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["label", "count", "ids"],
        "label": {"type": "string", "enum": CLAIM_LABELS},
        "count": {"type": "integer", "min": 0},
        "ids": {"type": "list", "items": {"type": "string", "pattern": CLAIM_ID}},
    }}},
    "defects": {"type": "list", "items": {"type": "string", "pattern": DEFECT_ID}},
    "disputes": {"type": "list", "items": {"type": "string", "pattern": CLAIM_ID}},
    "coverage": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["file", "metric", "before", "after", "target"],
        "file": {"type": "string"},
        "metric": {"type": "string", "enum": COVERAGE_METRICS},
        "before": {"type": "number", "min": 0, "max": 100},
        "after": {"type": "number", "min": 0, "max": 100, "nullable": True},
        "target": {"type": "number", "min": 0, "max": 100},
        "met": {"type": "boolean"},
    }}},
    # R-10.3 of the planning document gates concurrent execution on this measurement, which is
    # why it is a first-class section rather than a note. `declared_only` is footprint the item
    # never touched; `actual_only` is a file it touched that nothing declared, which R-2.2
    # makes an item failure rather than a footprint widening.
    "footprint": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["item", "declared_only", "actual_only"],
        "item": {"type": "string", "pattern": ITEM_ID},
        "declared_only": {"type": "list", "items": {"type": "string"}},
        "actual_only": {"type": "list", "items": {"type": "string"}},
    }}},
    "inherited_failures": {
        "type": "list",
        "items": {"type": "string"},
        "fix": "R-4.4: the failures pre-flight recorded before anything ran. The executor is "
               "responsible for causing no new red, not for repairing red it inherited.",
    },
    "narrowings": {
        "type": "list",
        "items": {"type": "mapping", "schema": {
            "_required": ["what", "cost"],
            "what": {"type": "string", "min_length": 10},
            "cost": {"type": "string", "min_length": 20},
        }},
        "fix": "R-10.3: every way the run narrowed its own scope, and what each narrowing "
               "cost. A partial run that reports honestly is a success mode; only silent "
               "omission is failure.",
    },
}

# --------------------------------------------------------------------------------------
# What the reporting and close-out stage writes
# --------------------------------------------------------------------------------------
#
# The same reasoning that put the execution writeback in this file puts the close-out records
# here. Stage four writes into the plan the owner reviewed and stage three wrote back into,
# and `plan_lint.py` is still the gate every one of those writes is checked against. A block
# the linter does not know is a block stage four cannot write, so the shapes live here and the
# rules live beside the execution rules in the linter, behind a fourth phase called `closed`.
#
# **The planner and the executor write none of them.** `premature-closeout-block` refuses every
# one of these at the three earlier phases, exactly as `premature-execution-block` refuses the
# execution blocks at the two before that.

# R-6.4's flag: a defect in a document rather than in code. It is tracked in the run ledger
# like any other finding until the document is amended or the flag is contested, which is why
# it carries an identifier of its own rather than living inside the close-out prose.
AMENDMENT_FLAG_SCHEMA = {
    "_required": ["id", "document", "passage"],
    "id": {"type": "string", "pattern": AMENDMENT_ID},
    "document": {
        "type": "string",
        "fix": "The requirements document now known to disagree with accepted behavior. A "
               "path, so the next person can open it.",
    },
    "passage": {
        "type": "string",
        "min_length": 20,
        "fix": "Quote the sentence that is now wrong. A flag naming only the document sends "
               "the reader to search a file for a disagreement they have to reconstruct.",
    },
    "location": {"type": "string", "fix": "`path:line` where the passage sits, when known."},
    "note": {"type": "string"},
}

# Where the known-failure marker went. Required for `downgrade` and forbidden elsewhere,
# because a marker nobody can find is a suite that reports green for a reason nobody can read.
MARKER_SCHEMA = {
    "_required": ["file", "form"],
    "file": {"type": "string"},
    "line": {"type": "integer", "min": 1},
    "form": {
        "type": "string",
        "min_length": 10,
        "fix": "The marker exactly as it was written — `@pytest.mark.xfail(reason=...)`, "
               "`it.failing(...)`, whichever the runner uses. It must name the defect "
               "identifier, so a reader who finds the marker can find the decision.",
    },
}

CLOSEOUT_SCHEMA = {
    "_required": [
        "id",
        "defect",
        "option",
        "decided-by",
        "date",
        "rationale",
        "red-test-state",
        "commit",
        "checks",
    ],
    "id": {"type": "string", "pattern": CLOSEOUT_ID},
    "defect": {"type": "string", "pattern": DEFECT_ID},
    "option": {
        "type": "string",
        "enum": CLOSEOUT_OPTIONS,
        "fix": "R-6.2's four answers. See references/closeout-brief.md for what each costs.",
    },
    "decided-by": {
        "type": "string",
        "min_length": 2,
        "fix": "The owner, by name. R-6.1 makes this the owner's answer and nobody else's; a "
               "decision with no decider is a decision an agent could have made.",
    },
    "date": {"type": "string"},
    "rationale": {
        "type": "string",
        "min_length": 30,
        "fix": "Why this answer rather than the other three. The next run re-reports an open "
               "defect and the reader needs to know what was already weighed.",
    },
    "red-test-state": {
        "type": "string",
        "enum": RED_TEST_STATES,
        "fix": "What this decision leaves the defect's test as: `standing` for the two "
               "options that change nothing, `rewritten` for `requirement-wrong`, `marked` "
               "for `downgrade`. Declared so the check runner can verify it.",
    },
    "commit": {
        "type": "string",
        "nullable": True,
        "fix": "The one commit this decision's transformation landed in, or null for the two "
               "options that apply nothing. R-6.2: one commit per decision.",
    },
    "checks": {
        "type": "list",
        "items": {"type": "mapping", "schema": RECORDED_CHECK_SCHEMA},
        "min_items": 1,
        "fix": "R-6.2: the check runner verifies each consequence before the gate advances. A "
               "close-out with no recorded outcome is a transformation nobody confirmed.",
    },
    "amendment-flag": {
        "type": "mapping",
        "schema": AMENDMENT_FLAG_SCHEMA,
        "fix": "Required by R-6.4 for `requirement-wrong` and meaningless for the other "
               "three. Accepting observed behavior means a document is now wrong, and the "
               "flag is what stops that being forgotten.",
    },
    "marker": {
        "type": "mapping",
        "schema": MARKER_SCHEMA,
        "fix": "Required for `downgrade` and forbidden for the other three.",
    },
    "note": {"type": "string"},
}

# R-6.5: the optional, non-blocking answer on an impeached pinned claim. A dispute is a planner
# error with evidence captured and nothing red on the branch, so leaving it undecided is a
# legitimate outcome — it stays an open ledger item and feeds the planner-accuracy finding.
DISPUTE_DECISION_OPTIONS = {"correct-the-claim", "leave-disputed"}

DISPUTE_DECISION_SCHEMA = {
    "_required": ["claim", "option", "decided-by", "date"],
    "claim": {"type": "string", "pattern": CLAIM_ID},
    "option": {
        "type": "string",
        "enum": DISPUTE_DECISION_OPTIONS,
        "fix": "`correct-the-claim` records replacement text for the next round of planning; "
               "`leave-disputed` records that the owner read it and chose to leave it. Both "
               "are answers. Only silence is not.",
    },
    "decided-by": {"type": "string", "min_length": 2},
    "date": {"type": "string"},
    "corrected-text": {
        "type": "string",
        "min_length": 20,
        "fix": "Required for `correct-the-claim`: the claim as it should have been written. "
               "It is not applied to the claim block — this run's claim records what this run "
               "asserted — it is carried to the ledger for the next plan to start from.",
    },
    "rationale": {"type": "string"},
}

# R-8.1's fixed taxonomy. Every pipeline finding is one of these five, and the categories are
# closed for the same reason the exclusion catalog is: an open category becomes a bucket for
# whatever did not fit, and a bucket is not a taxonomy.
FINDING_CATEGORIES = {
    "planning-gap",
    "assessment-staleness",
    "planner-claim-accuracy",
    "footprint-accuracy",
    "tooling-defect",
}

FINDING_STATES = {"open", "recurring", "retired", "contested"}

PIPELINE_FINDING_SCHEMA = {
    "_required": ["id", "category", "state", "summary", "evidence"],
    "id": {"type": "string", "pattern": FINDING_ID},
    "category": {
        "type": "string",
        "enum": FINDING_CATEGORIES,
        "fix": "See references/pipeline-findings.md, which gives a recognition test per "
               "category. A finding that fits none of them is a repository finding, not a "
               "pipeline one.",
    },
    "state": {"type": "string", "enum": FINDING_STATES},
    "summary": {"type": "string", "min_length": 20},
    "evidence": {
        "type": "string",
        "min_length": 20,
        "fix": "What in the run record establishes this. R-9.2: a finding is derived from the "
               "record, never from an impression of how the run felt.",
    },
    "first-seen": {"type": "string", "fix": "The run this was first raised in."},
    "occurrences": {"type": "integer", "min": 1},
    # What makes "the same finding" the same across runs. Two runs derive their findings
    # independently from their own records, so recognising a recurrence needs a key that both
    # derivations produce — the category plus the identifiers the finding is about. Matching on
    # the summary text instead would make a reworded sentence look like a new problem, which is
    # the failure R-8.2's recurrence flag exists to catch.
    "signature": {"type": "string"},
    "retired-by": {
        "type": "string",
        "nullable": True,
        "fix": "R-7.5: a finding is retired only explicitly, with the change that addressed "
               "it named here.",
    },
}

# Stage four's extension of stage three's run summary: the summary's own figures, plus the
# close-out decisions, their consequence commits, the final suite state, the pipeline findings,
# and the ledger entry this run appended.
#
# **Every figure the narrative report states comes from here** (R-5.1), which is what makes the
# tracer possible: a number in the prose that is not in this record is a number nobody computed.
RUN_RECORD_SCHEMA = {
    "_required": [
        "record_version",
        "summary_version",
        "closed",
        "branch",
        "items",
        "claims",
        "defects",
        "disputes",
        "coverage",
        "footprint",
        "inherited_failures",
        "narrowings",
        "decisions",
        "findings",
        "final_suite",
        "consistency",
    ],
    "record_version": {"type": "string", "enum": {"1.0"}},
    "summary_version": {"type": "string", "enum": {"1.0"}},
    "closed": {"type": "string", "fix": "The date the close-out gate completed."},
    "close_commit": {"type": "string", "nullable": True},
    "report_path": {"type": "string"},
    "plan_path": {
        "type": "string",
        "fix": "The plan this record describes. Carried into the run ledger so that a "
               "later plan linted against that ledger can tell whether it is the plan "
               "the ledger was built from — without it, R-7.3's claim rule fires on "
               "every claim of the plan that produced the entry.",
    },
    "branch": {"type": "string"},
    "base_commit": {"type": "string", "nullable": True},
    "started": {"type": "string"},
    "finished": {"type": "string"},
    # These six are copied forward from the run summary unchanged. Copied rather than
    # recomputed: R-4.1 forbids stage four re-deriving anything, and a second derivation that
    # disagreed with the first would be the drift this suite has already been bitten by twice.
    "items": RUN_SUMMARY_SCHEMA["items"],
    "claims": RUN_SUMMARY_SCHEMA["claims"],
    "defects": RUN_SUMMARY_SCHEMA["defects"],
    "disputes": RUN_SUMMARY_SCHEMA["disputes"],
    "coverage": RUN_SUMMARY_SCHEMA["coverage"],
    "footprint": RUN_SUMMARY_SCHEMA["footprint"],
    "inherited_failures": RUN_SUMMARY_SCHEMA["inherited_failures"],
    "narrowings": RUN_SUMMARY_SCHEMA["narrowings"],
    "decisions": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["id", "defect", "option", "commit"],
        "id": {"type": "string", "pattern": CLOSEOUT_ID},
        "defect": {"type": "string", "pattern": DEFECT_ID},
        "option": {"type": "string", "enum": CLOSEOUT_OPTIONS},
        "commit": {"type": "string", "nullable": True},
    }}},
    "dispute_decisions": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["claim", "option"],
        "claim": {"type": "string", "pattern": CLAIM_ID},
        "option": {"type": "string", "enum": DISPUTE_DECISION_OPTIONS},
    }}},
    "amendment_flags": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["id", "document"],
        "id": {"type": "string", "pattern": AMENDMENT_ID},
        "document": {"type": "string"},
        "passage": {"type": "string"},
    }}},
    "findings": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["id", "category", "state"],
        "id": {"type": "string", "pattern": FINDING_ID},
        "category": {"type": "string", "enum": FINDING_CATEGORIES},
        "state": {"type": "string", "enum": FINDING_STATES},
        "signature": {"type": "string"},
    }}},
    # What the suite does after every consequence landed. The report's second most-read figure
    # after coverage, and the one a reader will assume means "everything is fine" unless the
    # standing reds are stated beside it — so `expected_failures` is required rather than
    # optional, and it is legal for it to be empty only when `failing` is zero.
    "final_suite": {"type": "mapping", "schema": {
        "_required": ["command", "passed", "failed", "expected_failures"],
        "command": {"type": "string"},
        "passed": {"type": "integer", "min": 0, "nullable": True},
        "failed": {"type": "integer", "min": 0, "nullable": True},
        "expected_failures": {"type": "list", "items": {"type": "string"}},
        "measured": {
            "type": "boolean",
            "fix": "False when the suite could not be run at close-out. R-9.2: a figure that "
                   "was not measured is reported absent, never estimated.",
        },
        "log": {"type": "string", "fix": "Sidecar path holding the full run output (R-9.2)."},
        "note": {"type": "string"},
    }},
    # R-4.2's cross-check, recorded rather than only performed. Each entry is an inconsistency
    # between the plan writeback and the run summary, and each one degrades the report's stated
    # confidence — which is only possible if the report can see them.
    "consistency": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["check", "ok"],
        "check": {"type": "string"},
        "ok": {"type": "boolean"},
        "detail": {"type": "string"},
    }}},
    "ledger_entry": {"type": "mapping", "schema": {
        "_required": ["run_id", "path"],
        "run_id": {"type": "string"},
        "path": {"type": "string"},
        "open_items": {"type": "integer", "min": 0},
    }},
    "baseline_run": {
        "type": "string",
        "nullable": True,
        "fix": "R-7.4: the ledger run this one is a diff against, or null for a first run.",
    },
    "commit_distance": {
        "type": "integer",
        "min": 0,
        "nullable": True,
        "fix": "R-5.6's decay proxy: commits on the default branch since the previous "
               "close-out. Null on a first run, where there is nothing to measure from.",
    },
}

WORK_ITEM_SCHEMA = {
    "_required": [
        "id",
        "type",
        "slice",
        "title",
        "assessment-ref",
        "target",
        "depends-on",
        "files-touched",
        "global-effect",
        "completion-checks",
        "effort",
        "risk-tier",
        "status",
    ],
    "id": {"type": "string", "pattern": ITEM_ID, "fix": "Item ids look like `WI-03`."},
    "type": {"type": "string", "enum": ITEM_TYPES},
    "slice": {"type": "string", "pattern": SLICE_ID},
    "title": {"type": "string", "min_length": 10},
    "assessment-ref": {
        "type": "list",
        "items": {"type": "string", "pattern": ASSESSMENT_ID},
        "min_items": 1,
        "fix": "Every item descends from something in the assessment index. If it truly "
               "descends from nothing, it is out of scope for this plan.",
    },
    "target": {"type": "list", "items": {"type": "mapping", "schema": TARGET_SCHEMA}, "min_items": 1},
    "claims": {"type": "list", "items": {"type": "string", "pattern": CLAIM_ID}},
    "claims-enabled": {"type": "list", "items": {"type": "string", "pattern": CLAIM_ID}},
    "seam-type": {"type": "integer", "min": 1},
    "guarded-by": {"type": "string", "pattern": ITEM_ID},
    "guard-waiver": {"type": "string", "min_length": 20},
    "depends-on": {"type": "list", "items": {"type": "string", "pattern": ITEM_ID}},
    "files-touched": {"type": "mapping", "schema": FOOTPRINT_SCHEMA},
    "global-effect": {
        "type": "boolean",
        "fix": "True when the item changes something with repository-wide effect even "
               "though its footprint is small — coverage configuration, for instance.",
    },
    "completion-checks": {
        "type": "list",
        "items": {"type": "mapping", "schema": CHECK_SCHEMA},
        "min_items": 1,
    },
    "coverage-delta": {
        "type": "list",
        "items": {"type": "mapping", "schema": COVERAGE_DELTA_SCHEMA},
    },
    "mutation-waiver": {
        "type": "list",
        "items": {"type": "mapping", "schema": MUTATION_WAIVER_SCHEMA},
    },
    "effort": {"type": "mapping", "schema": EFFORT_SCHEMA},
    "risk-tier": {"type": "string", "enum": RISK_TIERS},
    "status": {"type": "string", "enum": STATUSES},
    "blocked-by": {
        "type": "list",
        "items": {"type": "string", "pattern": BLOCKER_ID},
    },
    "justification": {"type": "string", "min_length": 20},
    "notes": {"type": "string"},
    # R-7.3 of the reporting document: a plan that touches code carrying an open defect names
    # that defect in the affected items. The obligation is narrow on purpose — a planner is
    # entitled to plan nothing about an open defect, because fixing it may be somebody else's
    # work or scheduled for a later cycle. What is never legitimate is planning work *on top
    # of* one without saying so: the executor would then write tests in a file where something
    # is already known to be broken, and have no way to find that out.
    "known-defects": {
        "type": "list",
        "items": {"type": "string", "pattern": DEFECT_ID},
        "fix": "Defect identifiers from the run ledger, as `DF-1`. Run `plan_lint.py "
               "--ledger docs/test-ledger.json` to be told which items need which.",
    },
    # ---- written by stage three, never by the planner ----------------------------------
    "actuals": {
        "type": "mapping",
        "schema": ACTUALS_SCHEMA,
        "fix": "Recorded by the execution stage from the repository (R-9.1). The planner "
               "never writes it; the linter refuses it outside `--phase executed`.",
    },
    "commit": {
        "type": "string",
        "fix": "The commit this item's work landed in. Written by the execution stage.",
    },
    "diagnosis": {
        "type": "string",
        "min_length": 30,
        "fix": "R-6.1: what was attempted, what the check runner reported, and the executor's "
               "best explanation. Required on `failed`, `stale`, and `blocked-by-failure`.",
    },
}

CLAIM_SCHEMA = {
    "_required": ["id", "text", "label", "source", "locations"],
    "id": {"type": "string", "pattern": CLAIM_ID},
    "text": {
        "type": "string",
        "min_length": 20,
        "fix": "A claim must be precise enough to write a test from.",
    },
    "label": {"type": "string", "enum": CLAIM_LABELS},
    "source": {"type": "mapping", "schema": {
        "_required": ["kind"],
        "kind": {"type": "string", "enum": {"document", "code"}},
        "location": {"type": "string"},
        "quote": {"type": "string"},
    }},
    "locations": {
        "type": "list",
        "items": {"type": "string"},
        "min_items": 1,
        "fix": "Every claim names at least one `path:line` or `path` it applies to.",
    },
    "ratified-by": {"type": "string", "nullable": True},
    "ratified-on": {"type": "string", "nullable": True},
    "notes": {"type": "string"},
    # Written by stage three when it marks a claim `disputed` (R-7.5). A dispute impeaches
    # the planner's reading rather than the code, so it commits nothing red and the evidence
    # is the only thing the owner has to judge it by. A pointer, not the evidence itself: the
    # sidecar log or the side branch holding the test as written and the observed behavior.
    "evidence": {
        "type": "string",
        "min_length": 10,
        "fix": "A sidecar log path or a side-branch name. Required on a `disputed` claim, "
               "because a dispute with no evidence is an assertion that the planner was "
               "wrong, made by the party that would rather not write the test.",
    },
}

# What one answer does to the items it blocks. R-6.4 says what happens when a decision goes
# unresolved; this is what happens when it is resolved. Without it, an item that means
# different work under different answers has to smuggle the difference into prose — and a
# completion check qualified by a sentence saying "this check applies only under option b" is
# not machine-checkable as written, whatever R-7.1 asks for. The executor would have to
# interpret, which is the one thing the plan exists to prevent.
ITEM_EFFECT_SCHEMA = {
    "_required": ["item"],
    "item": {"type": "string", "pattern": ITEM_ID},
    "drop": {
        "type": "boolean",
        "fix": "True when the item does not exist at all under this answer.",
    },
    "set": {
        "type": "mapping",
        "schema": {"_allow_extra": True},
        "fix": "Field replacements, keyed by work-item field name. Validated against the "
               "work item schema, so `status: pending` is legal and `staus: pending` is not.",
    },
    "unset": {
        "type": "list",
        "items": {"type": "string"},
        "fix": "Field names to remove entirely. `set` replaces a value; `unset` deletes the "
               "field, which is what a seam losing its `guarded-by` needs.",
    },
    "remove-checks": {"type": "list", "items": {"type": "string", "enum": CHECK_KINDS}},
    "remove-claims": {"type": "list", "items": {"type": "string", "pattern": CLAIM_ID}},
    "add-claims": {"type": "list", "items": {"type": "string", "pattern": CLAIM_ID}},
    "note": {"type": "string"},
}

RESOLUTION_OPTION_SCHEMA = {
    "_required": ["id", "summary", "consequence"],
    "id": {"type": "string"},
    "summary": {"type": "string", "min_length": 10},
    "consequence": {"type": "string", "min_length": 10},
    "effect": {
        "type": "list",
        "items": {"type": "mapping", "schema": ITEM_EFFECT_SCHEMA},
        "fix": "Omit it entirely when the blocked items execute exactly as written under "
               "this answer. That is the default and it is common.",
    },
}

ESCALATION_SCHEMA = {
    "_required": ["id", "class", "title", "document-side", "code-side", "options", "blocks", "resolution"],
    "id": {"type": "string", "pattern": ESCALATION_ID},
    "class": {"type": "string", "enum": {"escalation"}},
    "title": {"type": "string", "min_length": 10},
    "document-side": {"type": "mapping", "schema": {
        "_required": ["location", "quote"],
        "location": {"type": "string"},
        "quote": {"type": "string"},
    }},
    "code-side": {"type": "mapping", "schema": {
        "_required": ["location", "quote"],
        "location": {"type": "string"},
        "quote": {"type": "string"},
    }},
    "options": {"type": "list", "items": {"type": "mapping", "schema": RESOLUTION_OPTION_SCHEMA}, "min_items": 2},
    "recommendation": {"type": "string", "nullable": True},
    "blocks": {
        "type": "list",
        "items": {"type": "string", "pattern": ITEM_ID},
        "min_items": 1,
        "fix": "An escalation that blocks nothing is not an escalation. If nothing depends "
               "on the answer, it is a flagged note instead.",
    },
    "resolution": {"type": "string", "nullable": True},
    "assessment-ref": {"type": "list", "items": {"type": "string", "pattern": ASSESSMENT_ID}},
}

DECISION_SCHEMA = {
    "_required": ["id", "class", "question", "context", "options", "blocks", "resolution"],
    "id": {"type": "string", "pattern": DECISION_ID},
    "class": {"type": "string", "enum": {"decision"}},
    "question": {"type": "string", "min_length": 15},
    "context": {"type": "string", "min_length": 20},
    "options": {"type": "list", "items": {"type": "mapping", "schema": RESOLUTION_OPTION_SCHEMA}, "min_items": 2},
    "recommendation": {"type": "string", "nullable": True},
    "blocks": {"type": "list", "items": {"type": "string", "pattern": ITEM_ID}, "min_items": 1},
    "resolution": {"type": "string", "nullable": True},
    "assessment-ref": {"type": "list", "items": {"type": "string", "pattern": ASSESSMENT_ID}},
}

FLAGGED_SCHEMA = {
    "_required": ["id", "class", "title", "documented-behavior", "evidence-of-absence", "note"],
    "id": {"type": "string", "pattern": FLAGGED_ID},
    "class": {"type": "string", "enum": {"flagged"}},
    "title": {"type": "string", "min_length": 10},
    "documented-behavior": {"type": "mapping", "schema": {
        "_required": ["location", "quote"],
        "location": {"type": "string"},
        "quote": {"type": "string"},
    }},
    "evidence-of-absence": {
        "type": "string",
        "min_length": 20,
        "fix": "State how you established that no code implements this — the searches you "
               "ran, not just the conclusion.",
    },
    "note": {"type": "string", "min_length": 20},
    "assessment-ref": {"type": "list", "items": {"type": "string", "pattern": ASSESSMENT_ID}},
}

EXCLUSION_SCHEMA = {
    "_required": ["id", "scope", "reason", "source"],
    "id": {"type": "string", "pattern": r"PX-[0-9]+"},
    "scope": {"type": "list", "items": {"type": "string"}, "min_items": 1},
    "reason": {"type": "string", "min_length": 20},
    "source": {"type": "string", "enum": {"inherited", "below-value-line", "planner"}},
    "assessment-ref": {"type": "list", "items": {"type": "string", "pattern": ASSESSMENT_ID}},
}

SLICE_SCHEMA = {
    "_required": ["id", "title", "area", "rationale", "items"],
    "id": {"type": "string", "pattern": SLICE_ID},
    "title": {"type": "string", "min_length": 5},
    "area": {"type": "string", "min_length": 3},
    "rationale": {"type": "string", "min_length": 20},
    "items": {"type": "list", "items": {"type": "string", "pattern": ITEM_ID}, "min_items": 1},
    "depends-on": {"type": "list", "items": {"type": "string", "pattern": SLICE_ID}},
    "deviation": {"type": "mapping", "schema": {
        "_required": ["kind", "justification"],
        "kind": {
            "type": "string",
            "enum": {"pulled-forward-for-seam", "demoted-fully-blocked"},
            "fix": "Only two deviations from risk order are permitted. See "
                   "references/slice-construction.md.",
        },
        "justification": {"type": "string", "min_length": 30},
    }},
}

PLAN_META_SCHEMA = {
    "_required": [
        "plan_version",
        "repository",
        "assessment_path",
        "assessment_commit",
        "generated",
        "value_line",
        "scope",
        "inherited_degradations",
    ],
    "plan_version": {"type": "string", "enum": {"1.0"}},
    "repository": {"type": "string"},
    "assessment_path": {"type": "string"},
    "assessment_commit": {"type": "string", "nullable": True},
    "generated": {"type": "string"},
    "value_line": {"type": "mapping", "schema": {
        "_required": ["lowest_tier_planned", "rationale"],
        "lowest_tier_planned": {"type": "string", "enum": RISK_TIERS},
        "rationale": {"type": "string", "min_length": 30},
    }},
    # How much of the reachable code this plan actually plans for, and why not the rest.
    #
    # The value line bounds which *findings* are planned for, and it turns out that is not the
    # same question as how much of the repository the plan touches. A plan can sit above the
    # value line on every finding, pass every completeness rule, and still reach a third of the
    # code — by routing the rest into the backlog, which the linter used to accept as coverage.
    # That happened: one real plan used fifteen of an available two hundred claims and deferred
    # two thirds of the repository without ever stating the proportion.
    #
    # Both figures are **recomputed by the linter** from the assessment's testability data and
    # the plan's own claim locations, exactly as the wave schedule is. The planner cannot write
    # a flattering number, and having to write the true one is the point: a rationale is only
    # worth reading beside the figure it is explaining.
    "scope": {"type": "mapping", "schema": {
        "_required": ["functions_planned", "functions_available", "rationale"],
        "functions_planned": {
            "type": "integer",
            "min": 0,
            "fix": "How many classified functions this plan's claims actually locate on. "
                   "Derived, not authored — run `plan_lint.py --scope` and paste it.",
        },
        "functions_available": {
            "type": "integer",
            "min": 0,
            "fix": "How many the assessment classified as reachable now or after a seam, "
                   "which is every category except `excluded` and `integration-only`.",
        },
        "rationale": {
            "type": "string",
            "min_length": 60,
            "fix": "Why the plan stops where it does. **`the rest is in the backlog` is not a "
                   "reason** — it says where the work went, not why it did not happen here. "
                   "Effort that will not fit a review sitting is a reason; work that is "
                   "merely more of the same is not.",
        },
    }},
    "inherited_degradations": {
        "type": "list",
        "items": {"type": "mapping", "schema": {
            "_required": ["id", "cost_to_this_plan"],
            "id": {"type": "string", "pattern": r"D[0-9]+"},
            "cost_to_this_plan": {
                "type": "string",
                "min_length": 20,
                "fix": "R-13.3 requires the plan to state what each inherited degradation "
                       "costs it, not merely that it inherited one.",
            },
        }},
    },
    "assessment_resolutions": {
        "type": "list",
        "items": {"type": "mapping", "schema": {
            "_required": ["ref", "issue", "resolution"],
            "ref": {"type": "string"},
            "issue": {"type": "string", "min_length": 20},
            "resolution": {"type": "string", "min_length": 20},
        }},
    },
    # Approval of the *plan*, which is not the same act as approval of the target and does not
    # live in the same place. `target.approved` approves a coverage number; this approves the
    # plan, and the review sitting also resolves escalations and ratifies claims (R-12.3).
    # Keeping them separate is deliberate: an owner may approve the plan while deferring the
    # number, which is exactly the re-baselining case `form: delta-with-rederivation` models.
    #
    # Execution R-4.1 reads this field and nothing else. An unapproved plan is never executed.
    "approved": {
        "type": "mapping",
        "schema": {
            "_required": ["by", "date"],
            "by": {"type": "string", "fix": "Who approved it. An approval with no approver "
                                            "is not an approval."},
            # `date`, not `on`, for the reason recorded on VERIFIER_RECORD_SCHEMA above.
            "date": {"type": "string"},
            "note": {"type": "string"},
        },
        "fix": "Written by the owner at the review sitting, never by the planner.",
    },
}

TARGET_PROPOSAL_SCHEMA = {
    "_required": ["form", "axes", "argument", "approved"],
    "form": {
        "type": "string",
        "enum": {"absolute", "delta", "delta-with-rederivation"},
        "fix": "Use `delta-with-rederivation` when slice zero changes the denominator, "
               "because an absolute target cannot be approved before the denominator exists.",
    },
    "axes": {"type": "list", "min_items": 1, "items": {"type": "mapping", "schema": {
        "_required": ["name", "metric", "from", "to"],
        "name": {"type": "string"},
        "metric": {"type": "string"},
        "from": {"type": "string"},
        "to": {"type": "string"},
        "basis": {"type": "string", "enum": {"measured", "estimated", "unknown"}},
    }}},
    "rederivation_trigger": {"type": "string", "nullable": True},
    "argument": {"type": "string", "min_length": 100},
    "approved": {"type": "string", "nullable": True},
}

WAVE_SCHEDULE_SCHEMA = {
    "_required": ["computed_by", "waves"],
    "computed_by": {"type": "string"},
    "note": {"type": "string"},
    "waves": {"type": "list", "items": {"type": "mapping", "schema": {
        "_required": ["wave", "slices"],
        "wave": {"type": "integer", "min": 1},
        "slices": {"type": "list", "items": {"type": "string", "pattern": SLICE_ID}, "min_items": 1},
        "reason": {"type": "string"},
    }}},
}

BACKLOG_SCHEMA = {
    "_required": ["id", "title", "reason", "assessment-ref"],
    "id": {"type": "string", "pattern": BACKLOG_ID},
    "title": {"type": "string", "min_length": 10},
    "reason": {"type": "string", "min_length": 20},
    "assessment-ref": {"type": "list", "items": {"type": "string", "pattern": ASSESSMENT_ID}},
}

BLOCK_SCHEMAS = {
    "plan-meta": PLAN_META_SCHEMA,
    "escalation": ESCALATION_SCHEMA,
    "decision": DECISION_SCHEMA,
    "flagged": FLAGGED_SCHEMA,
    "exclusion": EXCLUSION_SCHEMA,
    "target": TARGET_PROPOSAL_SCHEMA,
    "claim": CLAIM_SCHEMA,
    "slice": SLICE_SCHEMA,
    "work-item": WORK_ITEM_SCHEMA,
    "wave-schedule": WAVE_SCHEDULE_SCHEMA,
    "backlog-item": BACKLOG_SCHEMA,
    # Written by the execution stage. Phase-gated in plan_lint.py, so a plan that has not been
    # executed carrying one of these is a plan reporting on work that has not happened.
    "execution-log": EXECUTION_LOG_SCHEMA,
    "defect": DEFECT_SCHEMA,
    "run-summary": RUN_SUMMARY_SCHEMA,
    # Written by stage four at the close-out gate. Phase-gated the same way, one phase later.
    "close-out": CLOSEOUT_SCHEMA,
    "dispute-decision": DISPUTE_DECISION_SCHEMA,
    "pipeline-finding": PIPELINE_FINDING_SCHEMA,
    "run-record": RUN_RECORD_SCHEMA,
}

EXECUTION_BLOCKS = {"execution-log", "defect", "run-summary"}

CLOSEOUT_BLOCKS = {"close-out", "dispute-decision", "pipeline-finding", "run-record"}

SINGLETON_BLOCKS = {"plan-meta", "target", "wave-schedule", "run-summary", "run-record"}


def load_plan(path):
    """Read and parse a plan file. Returns (blocks_by_kind, problems, raw_text)."""
    problems = []
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as error:
        return {}, [Problem("unreadable", path, 0, str(error))], ""

    blocks = parse_blocks(text, path, problems)

    by_kind = {}
    for block in blocks:
        if block.kind not in BLOCK_SCHEMAS:
            problems.append(
                Problem(
                    "unknown-block",
                    path,
                    block.fence_line,
                    f"`yaml {block.kind}` is not a plan block type",
                    f"Known types: {', '.join(sorted(BLOCK_SCHEMAS))}.",
                )
            )
            continue
        by_kind.setdefault(block.kind, []).append(block)

    for kind in SINGLETON_BLOCKS:
        found = by_kind.get(kind, [])
        if len(found) > 1:
            for block in found[1:]:
                problems.append(
                    Problem(
                        "duplicate-block",
                        path,
                        block.fence_line,
                        f"a plan carries exactly one `{kind}` block; this is number "
                        f"{found.index(block) + 1}",
                    )
                )

    return by_kind, problems, text

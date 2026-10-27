#!/usr/bin/env python3
"""The shell guard: PreToolUse on Bash.

Two kinds of command hang a tool shell forever, and written rules against both
failed repeatedly, three times in one week, each time inside a subagent whose
brief did not repeat the rule. So the harness refuses them instead.

1. A plain `cp`, `mv` or `rm`. The tool shell copies the user's shell setup,
   where prezto's utility module aliases all three to their `-i` forms. A prompt
   in a tool shell has nobody to answer it, so the command waits forever. Any
   of these passes: a `-f` or `--force` flag (the last of `-i` and `-f` wins on
   macOS), a `command` prefix, a leading backslash, or an absolute path such as
   `/bin/rm`, since each of the last three skips the alias.

2. A `while` or `until` loop that sleeps. Its condition may never come true,
   so it may never end. A poll is the right way to wait, but it needs a fixed
   number of rounds: a `for` loop over `$(seq N)` that breaks when the check
   passes always ends.

3. A `tail` that follows a file (`-f`, `-F` or `--follow`). It never exits on
   its own. Piped into `grep -m1`, it outlives the grep, because it dies only
   when it next writes and the file may never grow again. On 26 October 2026
   one sat for almost four hours after its command had finished (#349 in
   attitude-problem).

Failing open is the deliberate direction, as in plan-request-guard.sh: input
this script cannot read or a command it cannot parse is allowed, so a guard
that cannot read its own input can never wedge a session.
"""

import json
import re
import shlex
import sys

ALIASED = {"cp", "mv", "rm"}
LOOPS = {"while", "until"}
# Words that may stand before the command name without being the command.
PREFIXES = {
    "then", "do", "else", "elif", "if", "!", "{", "time", "nohup", "sudo",
    "env", "exec", "nocorrect", "noglob", "builtin",
}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "$(", "`", "|&", ";;"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredocs(command):
    """Drops the body of every heredoc, which is data rather than commands."""
    lines = command.split("\n")
    kept = []
    ending = []
    for line in lines:
        if ending:
            if line.strip() == ending[0]:
                ending.pop(0)
            continue
        kept.append(line)
        ending.extend(match.group(2) for match in HEREDOC.finditer(line))
    return "\n".join(kept)


def command_words(command):
    """The first word of every simple command, with the words after it."""
    lexer = shlex.shlex(
        command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()`"
    )
    lexer.whitespace_split = True
    tokens = list(lexer)
    commands = []
    current = []
    for token in tokens:
        if token in SEPARATORS or token.endswith("$"):
            # `$(` reaches here as a `$` glued to the word before it, or alone.
            if current:
                commands.append(current)
            current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    words = []
    for words_of_one in commands:
        i = 0
        while i < len(words_of_one) and (
            words_of_one[i] in PREFIXES or ASSIGNMENT.match(words_of_one[i])
        ):
            i += 1
        if i < len(words_of_one):
            words.append((words_of_one[i], words_of_one[i + 1 :], words_of_one[:i]))
    return words


def forced(arguments):
    for argument in arguments:
        if argument == "--":
            return False
        if argument == "--force":
            return True
        if argument.startswith("-") and not argument.startswith("--") and "f" in argument:
            return True
    return False


def follows(arguments):
    for argument in arguments:
        if argument == "--":
            return False
        if argument.startswith("--follow"):
            return True
        if argument.startswith("-") and not argument.startswith("--") and (
            "f" in argument or "F" in argument
        ):
            return True
    return False


POLL = (
    "Poll with a fixed number of rounds instead, for example "
    "`for i in $(seq 60); do grep -q '^rc=' FILE && break; sleep 30; done`, "
    "run in the background so its exit notifies you, or check once per call."
)


def refusal(raw):
    # A leading backslash skips the alias, but a POSIX lexer would swallow it.
    raw = re.sub(r"(^|[\s;&|(`])\\(cp|mv|rm)\b", r"\1command \2", raw)
    try:
        words = command_words(strip_heredocs(raw))
    except ValueError:
        return None
    names = [name for name, _, _ in words]
    if any(name in LOOPS for name in names) and "sleep" in names:
        return (
            "SHELL GUARD: this command sleeps in a while or until loop, which "
            "never ends if its condition never comes true; three such shells "
            "were left hanging for days. " + POLL
        )
    for name, arguments, _ in words:
        if name == "tail" and follows(arguments):
            return (
                "SHELL GUARD: `tail` that follows a file never exits on its own, "
                "and piped into `grep -m1` it outlives the grep for hours. " + POLL
            )
    for name, arguments, before in words:
        if name in ALIASED and "command" not in before and not forced(arguments):
            return (
                f"SHELL GUARD: plain `{name}` is aliased to `{name} -i` in this shell, "
                "and an overwrite or delete prompt here has nobody to answer it, so "
                f"the command hangs forever. Write `{name} -f ...` or "
                f"`command {name} ...` instead."
            )
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        raw = payload.get("tool_input", {}).get("command", "")
        reason = refusal(raw) if isinstance(raw, str) else None
    except Exception:
        return
    if reason:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            sys.stdout,
        )


if __name__ == "__main__":
    main()

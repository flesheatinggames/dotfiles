#!/usr/bin/env bash
#
# The plan-mode guard.
#
# Projects/CLAUDE.md says that "plan" means use planning mode. That written rule
# has failed repeatedly on its own, so this script makes the harness enforce it
# rather than leaving it to be remembered.
#
# Three modes, one per hook:
#
#   prompt  UserPromptSubmit. If the submitted prompt reads as an imperative
#           request for a plan, write a session-scoped sentinel and inject an
#           instruction to call EnterPlanMode before any other tool call. If it
#           does not, remove the sentinel, so a sentinel never outlives its turn.
#   clear   PreToolUse on EnterPlanMode. Planning mode was entered; the sentinel
#           has done its work and goes away. Always allows.
#   guard   PreToolUse on Edit, Write and NotebookEdit. While a sentinel exists,
#           deny with a reason that names the rule. Bash is deliberately not
#           guarded: exploring the codebase is read-only and must stay possible.
#
# Failing open is the deliberate direction. Every unexpected condition exits 0
# with no output, which is "allow" — a guard that cannot read its own input must
# not be able to wedge a session.

set -uo pipefail

STATE_DIR="$HOME/.claude/plan-guard"

input=$(cat)
session=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
# The session identifier reaches the filesystem as a path component, so anything
# that is not plainly a name is replaced rather than trusted. An empty result —
# unreadable input, or no identifier at all — must not collapse the path onto the
# state directory itself, which exists as soon as anything has been written and
# would then read as a sentinel for every session at once.
session=$(printf '%s' "$session" | tr -c 'A-Za-z0-9._-' '_')
[ -n "$session" ] || session=unknown
sentinel="$STATE_DIR/$session"

case "${1:-}" in
  prompt)
    prompt=$(printf '%s' "$input" | jq -r '.prompt // empty' 2>/dev/null)
    if printf '%s' "$prompt" | grep -qiE '(^[[:space:]]*/?plan([[:space:]]|$))|((make|write|create|draft|do) (me )?an? plan)|(let'"'"'?s plan)|(plan (it|this|that) out)|((can|could) you plan)|(please plan)'; then
      mkdir -p "$STATE_DIR" 2>/dev/null
      : > "$sentinel" 2>/dev/null
      jq -n '{
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit",
          additionalContext: "PLAN-MODE GUARD: this prompt is a request for a plan. Per Projects/CLAUDE.md, \"plan\" means use planning mode. Call the EnterPlanMode tool NOW, before any other tool call — before reading files, before searching, before asking a clarifying question. Editing tools are blocked until you do."
        }
      }'
    else
      rm -f "$sentinel" 2>/dev/null
    fi
    ;;
  clear)
    rm -f "$sentinel" 2>/dev/null
    ;;
  guard)
    # A plain file, never a directory: only something this script wrote counts.
    if [ -f "$sentinel" ]; then
      tool=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)
      [ -n "$tool" ] || tool="This tool"
      jq -n --arg tool "$tool" '{
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: ($tool + " is blocked: the user asked for a plan, and Projects/CLAUDE.md says \"plan\" means use planning mode. Call EnterPlanMode first. Reading and searching are still allowed.")
        }
      }'
    fi
    ;;
esac

exit 0

#!/bin/zsh
# Herdr restores workspaces, tabs, panes, cwd, layout, focus and native agent
# sessions - but not arbitrary processes, which come back as bare shells. It
# does persist each pane's label, so a label is enough to remember what a pane
# was for and start it again here.
#
# Label a pane with:  herdr pane rename <pane_id> editor

emulate -L zsh
set -u

herdr=${HERDR_BIN_PATH:-herdr}

# label -> command to relaunch in any pane carrying that label.
typeset -A RESTORE=(
  editor 'nvim .'
)

# A pane counts as ready only when its foreground process is nothing but a
# shell. Anything else means something is already running there.
typeset -a SHELLS=( zsh bash sh fish -zsh -bash -sh )

READY_TIMEOUT=15   # seconds to wait for a restored pane's shell to come up
SETTLE=2           # seconds to let restored shells finish their own startup

PANE_PROCS=""

(( $+commands[jq] )) || { print -u2 "restore-panes: jq is required"; exit 1; }

# Sets PANE_PROCS to whatever is in the foreground, so a skip can say why.
pane_ready() {
  local n
  PANE_PROCS=$("$herdr" pane process-info --pane "$1" 2>/dev/null \
    | jq -r '.result.process_info.foreground_processes[]?.name' | paste -sd, -)
  [[ -n $PANE_PROCS ]] || return 1
  for n in ${(s:,:)PANE_PROCS}; do
    (( ${SHELLS[(Ie)$n]} )) || return 1
  done
  return 0
}

# Collect targets first: every labelled, agentless pane whose label is mapped.
# Agent panes are skipped because Herdr resumes those itself.
typeset -a targets
for ws in $("$herdr" workspace list | jq -r '.result.workspaces[].workspace_id'); do
  while IFS=$'\t' read -r pane label; do
    [[ -n ${RESTORE[$label]:-} ]] && targets+=( "$pane"$'\t'"$label" )
  done < <("$herdr" pane list --workspace "$ws" \
    | jq -r '.result.panes[] | select(.label != null and .agent == null)
             | "\(.pane_id)\t\(.label)"')
done

(( ${#targets} )) || { print "restore-panes: nothing labelled to restore"; exit 0; }

# Restored panes exist before their shells have finished starting up, and a
# login shell can briefly show its own helper processes in the foreground.
sleep $SETTLE

for entry in $targets; do
  pane=${entry%%$'\t'*}
  label=${entry#*$'\t'}
  cmd=${RESTORE[$label]}

  # The pane exists before its shell is necessarily accepting input.
  waited=0
  while ! pane_ready "$pane"; do
    (( waited >= READY_TIMEOUT )) && break
    sleep 1
    (( waited += 1 ))
  done

  if pane_ready "$pane"; then
    "$herdr" pane run "$pane" "$cmd" >/dev/null \
      && print "restore-panes: ran '$cmd' in $pane ($label)"
  else
    print "restore-panes: skipped $pane ($label), foreground = ${PANE_PROCS:-none}"
  fi
done

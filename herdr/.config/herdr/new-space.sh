#!/bin/zsh
# Create a Herdr space rooted at a path, laid out 50/50 with nvim on the
# left and ccd on the right.
#
#   new-space.sh [path]
#
# With no argument it prompts. Bound to prefix+shift+s in config.toml.

emulate -L zsh
set -u

herdr=${HERDR_BIN_PATH:-herdr}

die() { print -u2 "new-space: $*"; sleep 3; exit 1; }

# Root the fzf picker searches. Override per-invocation if you ever need to.
: ${NEW_SPACE_ROOT:=$HOME/Projects}

# Pick a project with fzf: the root itself first, then its immediate
# subdirectories newest-first. --print-query means a path typed by hand is
# accepted even when it matches nothing in the list.
pick_dir() {
  local -a choices
  choices=( $NEW_SPACE_ROOT $NEW_SPACE_ROOT/*(/Nom) )
  local out
  out=$(print -rl -- ${choices/#$HOME/\~} \
    | fzf --print-query --reverse --height=100% \
          --prompt='new space > ' --header='enter a path, or pick one')
  local -a lines
  lines=( ${(f)out} )
  # Line 2 is the selection when one was made; line 1 is the raw query.
  print -r -- ${lines[2]:-${lines[1]:-}}
}

dir=${1:-}
if [[ -z $dir ]]; then
  if (( $+commands[fzf] )); then
    dir=$(pick_dir)
  else
    print -n "path for new space: "
    read -r dir || exit 1
  fi
fi

# Expand ~ and any leading variable, then resolve to an absolute path.
dir=${~dir}
[[ -n $dir ]] || exit 0
[[ -d $dir ]] || die "not a directory: $dir"
dir=${dir:A}

# workspace.create can transiently report ui_busy while a modal popup is still
# on screen, so give it a few attempts before giving up.
for attempt in 1 2 3; do
  created=$("$herdr" workspace create --cwd "$dir" --label "${dir:t}" --focus 2>&1) && break
  created=""
  sleep 0.4
done
[[ -n $created ]] || die "could not create space: see herdr-server.log"

root=$(print -r -- "$created" | jq -r '.result.root_pane.pane_id')
[[ $root == null || -z $root ]] && die "no root pane in create response"

right=$("$herdr" pane split "$root" --direction right --ratio 0.5 --no-focus \
  | jq -r '.result.pane.pane_id')
[[ $right == null || -z $right ]] && die "split failed"

"$herdr" pane run "$root"  "nvim ." >/dev/null
"$herdr" pane run "$right" "ccd"    >/dev/null

# Focus stays on the root (nvim) pane, since the split above used --no-focus.
# To land in ccd instead, change that --no-focus to --focus.

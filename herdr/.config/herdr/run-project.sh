#!/bin/zsh
# Start (or restart) this project's run command in a background "run" tab, so a
# dev server or a game does not take over the pane you talk to the agent in.
#
#   run-project.sh          run the remembered command, else the default
#   run-project.sh -p       pick a variant with fzf (or type one), then run it
#   run-project.sh -n       print what would run and exit
#
# Candidates come from a .herdr-run file at the project root when there is one -
# every non-comment line is a variant, the first is the default - otherwise a
# single command is guessed from the project's build files. Whatever runs is
# remembered per project, so plain presses restart the variant you last chose.
#
# Bound to prefix+shift+e (run) and prefix+shift+f (pick) in config.toml.

emulate -L zsh
set -u

herdr=${HERDR_BIN_PATH:-herdr}
ws=${HERDR_ACTIVE_WORKSPACE_ID:-${HERDR_WORKSPACE_ID:-}}
cwd=${HERDR_ACTIVE_PANE_CWD:-$PWD}

TAB_LABEL=run
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/herdr-run/history

mode=run
case ${1:-} in
  -p) mode=pick ;;
  -n) mode=dry ;;
esac

die() { print -u2 "run-project: $*"; [[ $mode == dry ]] || sleep 4; exit 1; }

find_root() {
  local d=$1 m
  while [[ $d == /* && $d != / ]]; do
    for m in .herdr-run Cargo.toml package.json go.mod justfile Justfile Makefile pyproject.toml; do
      [[ -e $d/$m ]] && { print -r -- "$d"; return 0 }
    done
    d=${d:h}
  done
  return 1
}

# Every variant this project offers, best-guess default first.
candidates() {
  local r=$1 pm s
  if [[ -f $r/.herdr-run ]]; then
    grep -vE '^[[:space:]]*(#|$)' "$r/.herdr-run"
    return
  fi
  [[ -f $r/Cargo.toml ]] && { print -r -- "cargo run"; return }
  if [[ -f $r/package.json ]] && (( $+commands[jq] )); then
    pm=npm
    [[ -f $r/pnpm-lock.yaml ]] && pm=pnpm
    [[ -f $r/yarn.lock ]]      && pm=yarn
    [[ -f $r/bun.lockb ]]      && pm=bun
    for s in dev start serve; do
      jq -e --arg s $s '.scripts | has($s)' "$r/package.json" >/dev/null 2>&1 \
        && print -r -- "$pm run $s"
    done
    return
  fi
  [[ -f $r/go.mod ]] && { print -r -- "go run ."; return }
  if [[ -f $r/justfile || -f $r/Justfile ]] && (( $+commands[just] )); then
    just --justfile "$r"/[jJ]ustfile --summary 2>/dev/null | tr ' ' '\n' | grep -qx run \
      && { print -r -- "just run"; return }
  fi
  [[ -f $r/Makefile ]] && grep -qE '^run[[:space:]]*:' "$r/Makefile" \
    && { print -r -- "make run"; return }
  return 1
}

remembered() { [[ -f $STATE ]] && awk -F'\t' -v r="$1" '$1==r{c=$2} END{if(c)print c}' "$STATE" }

remember() {
  mkdir -p "${STATE:h}"
  local tmp=$STATE.$$
  [[ -f $STATE ]] && awk -F'\t' -v r="$1" '$1!=r' "$STATE" > "$tmp" || : > "$tmp"
  printf '%s\t%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$STATE"
}

root=$(find_root "$cwd") || die "no project markers above $cwd"
typeset -a cands
cands=( ${(f)"$(candidates "$root")"} )
last=$(remembered "$root")

if [[ $mode == pick ]]; then
  (( $+commands[fzf] )) || die "fzf is required for -p"
  # Remembered choice first so re-picking the same thing is one keypress.
  typeset -a menu
  [[ -n $last ]] && menu+=( "$last" )
  local c
  for c in $cands; do [[ $c == $last ]] || menu+=( "$c" ); done
  (( ${#menu} )) || menu=( "" )
  out=$(print -rl -- $menu | fzf --print-query --reverse --height=100% \
        --prompt="run ${root:t} > " --header='pick a variant, or type a command')
  typeset -a lines; lines=( ${(f)out} )
  cmd=${lines[2]:-${lines[1]:-}}
  [[ -n $cmd ]] || exit 0
else
  cmd=${last:-${cands[1]:-}}
  [[ -n $cmd ]] \
    || die "don't know how to run ${root:t}; add a .herdr-run file with the command"
fi

if [[ $mode == dry ]]; then
  print -r -- "root:       $root"
  print -r -- "cmd:        $cmd"
  print -r -- "remembered: ${last:-(none)}"
  print -r -- "variants:   ${(j:, :)cands}"
  exit 0
fi

[[ -n $ws ]] || die "no active workspace"

tab=$("$herdr" tab list --workspace "$ws" \
  | jq -r --arg l "$TAB_LABEL" '.result.tabs[] | select(.label == $l) | .tab_id' | head -1)

if [[ -n $tab ]]; then
  pane=$("$herdr" pane list --workspace "$ws" \
    | jq -r --arg t "$tab" '.result.panes[] | select(.tab_id == $t) | .pane_id' | head -1)
  "$herdr" pane send-keys "$pane" ctrl+c >/dev/null 2>&1 || true
  sleep 1
else
  pane=$("$herdr" tab create --workspace "$ws" --label "$TAB_LABEL" --cwd "$root" --no-focus \
    | jq -r '.result.root_pane.pane_id')
  [[ -n $pane && $pane != null ]] || die "could not create the $TAB_LABEL tab"
fi

remember "$root" "$cmd"
"$herdr" pane run "$pane" "cd ${(q)root} && $cmd" >/dev/null \
  && print "run-project: $cmd  ->  $pane (${root:t})"

#!/bin/zsh
session_name="main-$(date +%s)"
tmux new-session -d -s "$session_name" -x "$(tput cols)" -y "$(tput lines)"
tmux split-window -h -p 30
tmux split-window -v -p 25
tmux select-pane -t 0
tmux attach-session -t "$session_name"

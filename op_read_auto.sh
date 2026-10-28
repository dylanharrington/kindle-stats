#!/bin/bash
# Wrapper for `op read` that auto-approves the 1Password authorization dialog.
#
# Opt-in only: used when config.json sets "op_auto_approve": true.
# It presses Space in whatever app is frontmost two seconds after starting,
# which skips a 1Password security prompt. Prefer approving the prompt
# yourself, or use a 1Password service account for unattended runs.

# Run op read in background
op read "$@" &
PID=$!

# Wait for auth dialog to appear and send spacebar
sleep 2
osascript -e 'tell application "System Events" to keystroke space' 2>/dev/null

# Wait for process to complete
wait $PID

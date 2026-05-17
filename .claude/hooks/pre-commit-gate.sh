#!/bin/bash
# Blocks git commit unless make format was run recently (<30 min).
# Staged in hooks/STAGED.example.json — not yet wired in settings.json.
# Works with post-bash-track.sh which creates the gate flag files.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only check git commit commands
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

GATE_DIR="$CLAUDE_PROJECT_DIR/.claude/.gates"
NOW=$(date +%s)
MAX_AGE=1800  # 30 minutes

check_gate() {
  local file="$1"
  local name="$2"
  if [ ! -f "$file" ]; then
    echo "BLOCKED: '$name' has not been run. Execute it before committing." >&2
    exit 2
  fi
  local age=$((NOW - $(stat -f %m "$file")))
  if [ "$age" -gt "$MAX_AGE" ]; then
    echo "BLOCKED: '$name' was run more than 30 minutes ago. Run it again before committing." >&2
    exit 2
  fi
}

check_gate "$GATE_DIR/format-passed" "make format"

exit 0

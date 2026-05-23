#!/bin/bash
# Blocks an actual `git commit` unless a format check ran recently (<30 min):
# make format (auto-fix) or make verify / make lint (format check).
# Wired: PreToolUse/Bash in settings.json. Pairs with post-bash-track.sh.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only gate an actual `git commit` invocation — not any command that merely mentions
# the string (echo, comments, --grep, file paths). Anchor to a command boundary.
if ! echo "$COMMAND" | grep -qE '(^|[;&|])[[:space:]]*git[[:space:]]+commit([[:space:]]|$)'; then
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

check_gate "$GATE_DIR/format-passed" "make format / make verify / make lint"

exit 0

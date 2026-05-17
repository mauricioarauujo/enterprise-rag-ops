#!/bin/bash
# Tracks successful quality gate execution.
# Wired via PostToolUse hook on Bash commands in settings.json.
# Creates flag files that pre-commit-gate.sh checks before allowing commits.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
GATE_DIR="$CLAUDE_PROJECT_DIR/.claude/.gates"
mkdir -p "$GATE_DIR"

if echo "$COMMAND" | grep -q 'make format'; then
  touch "$GATE_DIR/format-passed"
fi

if echo "$COMMAND" | grep -qE 'make test|uv run pytest|pytest'; then
  touch "$GATE_DIR/test-passed"
fi

exit 0

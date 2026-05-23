#!/bin/bash
# Tracks quality-gate command invocations (wired: PostToolUse/Bash in settings.json).
# Creates flag files that pre-commit-gate.sh checks before allowing commits.
# Invocation-based by necessity: the PostToolUse payload carries no exit code
# (tool_response = stdout/stderr/interrupted only), so this records that a check
# RAN recently, not that it passed.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
GATE_DIR="$CLAUDE_PROJECT_DIR/.claude/.gates"
mkdir -p "$GATE_DIR"

# `make format` applies formatting; `make verify` / `make lint` run the format
# CHECK (ruff + prettier, no auto-fix). Any of them satisfies the format gate.
# (Makefile: `verify: lint test` — verify does NOT call format.)
if echo "$COMMAND" | grep -qE 'make format|make verify|make lint'; then
  touch "$GATE_DIR/format-passed"
fi

if echo "$COMMAND" | grep -qE 'make test|make verify|uv run pytest|pytest'; then
  touch "$GATE_DIR/test-passed"
fi

exit 0

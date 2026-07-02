#!/usr/bin/env bash
# PostToolUse(Bash): records that a quality gate ran successfully (fires only on exit 0).
# Records the EXACT working-tree hash the gate validated (diff-bound) into a flag file that
# commit-gate.sh re-checks. Tune GATE_RE to your project's gate commands. Ships inert.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
GATE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/.gates"
mkdir -p "$GATE_DIR"
REPO="${CLAUDE_PROJECT_DIR:-$PWD}"

# Tunable: the commands that count as "the gate passed".
GATE_RE='make (format|test|lint)|prettier|ruff|pytest|npm (test|run lint)'
if echo "$COMMAND" | grep -qE "$GATE_RE"; then
  # Hash HEAD + staged/unstaged/untracked — the precise tree state this gate run validated.
  (cd "$REPO" && { git rev-parse HEAD; git status --porcelain; git diff HEAD; } 2>/dev/null | { shasum 2>/dev/null || sha1sum; } | awk '{print $1}') >"$GATE_DIR/gate-passed"
fi
exit 0

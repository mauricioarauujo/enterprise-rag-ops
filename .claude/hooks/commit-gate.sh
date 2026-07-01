#!/usr/bin/env bash
# PreToolUse(Bash): blocks `git commit` unless a quality gate validated THIS EXACT tree,
# proven by the tree-hash gate-track.sh records. Diff-bound, not time-bound: a gate that
# passed on different code (even 1 second ago) does NOT satisfy it — any edit after the gate
# invalidates it. exit 2 = block; exit 0 = proceed. Ships inert (see hooks/README.md).

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
echo "$COMMAND" | grep -q 'git commit' || exit 0

GATE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/.gates"
FLAG="$GATE_DIR/gate-passed"
REPO="${CLAUDE_PROJECT_DIR:-$PWD}"

if [ ! -f "$FLAG" ]; then
  echo "BLOCKED: the quality gate (e.g. make format/test) has not run. Run it before committing." >&2
  exit 2
fi
# Hash the exact working-tree state (HEAD + staged/unstaged/untracked) the same way gate-track does.
current=$(cd "$REPO" && { git rev-parse HEAD; git status --porcelain; git diff HEAD; } 2>/dev/null | { shasum 2>/dev/null || sha1sum; } | awk '{print $1}')
recorded=$(cat "$FLAG" 2>/dev/null)
if [ "$current" != "$recorded" ]; then
  echo "BLOCKED: the working tree changed since the quality gate passed. Re-run the gate, then commit." >&2
  exit 2
fi
exit 0

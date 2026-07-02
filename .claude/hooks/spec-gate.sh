#!/usr/bin/env bash
# Kbind maker≠checker gate (building block — ready-but-inert; see hooks/README.md).
# Runs the repo's Spec status-ladder check and BLOCKS (exit 2) on a violation, so a
# generative step can't proceed over a broken Spec contract. Wire it from your repo's
# .claude/settings.json (the plugin ships it inert). Exit 0 = proceed; exit 2 = block.
set -euo pipefail

repo_root="${CLAUDE_PROJECT_DIR:-$PWD}"
checker="$repo_root/docs/specs/check_spec_status.py"

# No specs layer in this repo → nothing to gate; proceed silently.
[ -f "$checker" ] || exit 0

if python3 "$checker" "$repo_root/docs/specs" >/tmp/kbind-spec-gate.out 2>&1; then
  exit 0
fi

echo "BLOCKED by kbind spec-gate — the Spec status ladder is violated:" >&2
cat /tmp/kbind-spec-gate.out >&2
echo "Fix the spec(s) above (or run audit-harness), then retry." >&2
exit 2

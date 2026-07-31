#!/usr/bin/env bash
# Kbind maker≠checker gate (building block — ready-but-inert; see hooks/README.md).
# Runs the repo's Spec status-ladder check and BLOCKS (exit 2) on a violation, so a
# generative step can't proceed over a broken Spec contract. Wire it from your repo's
# .claude/settings.json (the plugin ships it inert). Exit 0 = proceed; exit 2 = block.
#
# The specs area is RESOLVED, never assumed. This hook used to hardcode `docs/specs/`, which
# meant that in a repo remapping its spec area through contract-v1 `layout:` the checker was
# simply not at the expected path — so the hook took its "no specs layer" branch and exited 0
# having examined nothing, indistinguishable from a repo that genuinely has no specs. Measured
# live in a consumer whose specs sit at `.claude/sdd/`: a maker≠checker gate, silently inert.
#
# It calls the SEEDED resolver (`.claude/scripts/layout_lib.py`) rather than the plugin's copy:
# a git hook runs inside the checked-out repo and cannot rely on ${CLAUDE_PLUGIN_ROOT}.
#
# NOTHING HERE BLOCKS ON ABSENCE. Every "can't check" path exits 0 — but says so. Reporting is
# compatible with ADR-0007/D19: inertness there means the plugin activates no hook on anyone
# (hooks/README.md: "Installing the plugin activates no hook on anyone"), not that a hook a
# consumer deliberately wired must stay mute. This hook already writes to stderr when it blocks.
set -euo pipefail

repo_root="${CLAUDE_PROJECT_DIR:-$PWD}"
resolver="$repo_root/.claude/scripts/layout_lib.py"

# A green that examined nothing reports the circle, never the check — including in a hook.
if [ ! -f "$resolver" ]; then
  echo "○ kbind spec-gate examined nothing — $resolver is missing, so the specs area cannot be" >&2
  echo "  resolved. Run /kbind:harness-update to sync the seeds. (Proceeding; not a gate failure.)" >&2
  exit 0
fi

# stderr is deliberately NOT swallowed: the resolver warns there when a manifest exists but could
# not be parsed, i.e. when the path below is a default wearing the look of a resolution.
if ! specs_dir=$(python3 "$resolver" "$repo_root" specs_index --dir); then
  echo "○ kbind spec-gate examined nothing — the specs area could not be resolved from" >&2
  echo "  .claude/kbind.yaml. (Proceeding; not a gate failure.)" >&2
  exit 0
fi

checker="$repo_root/$specs_dir/check_spec_status.py"

# Two different states that used to look identical. Both proceed; neither is silent.
if [ ! -f "$checker" ]; then
  if [ -d "$repo_root/$specs_dir" ]; then
    echo "○ kbind spec-gate examined nothing — specs area '$specs_dir' exists but carries no" >&2
    echo "  check_spec_status.py. Run /kbind:harness-update to seed it. (Proceeding.)" >&2
  else
    echo "○ kbind spec-gate: no specs layer at '$specs_dir' — nothing to gate. (Proceeding.)" >&2
  fi
  exit 0
fi

if python3 "$checker" "$repo_root/$specs_dir" >/tmp/kbind-spec-gate.out 2>&1; then
  exit 0
fi

echo "BLOCKED by kbind spec-gate — the Spec status ladder is violated:" >&2
cat /tmp/kbind-spec-gate.out >&2
echo "Fix the spec(s) above (or run audit-harness), then retry." >&2
exit 2

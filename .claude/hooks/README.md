# hooks/ — maker≠checker gates + context hygiene, ready-but-inert

Kbind ships the **building blocks** for mechanically-enforced gates, **not automations**
(ADR-0007 / D19). Installing the plugin activates **no hook on anyone** — there is
intentionally no active `hooks.json`. Each hook is a tunable a consumer opts into; the human
sign-off gate (`sign-off-phase`) stays interactive by design.

## The exit-code-2 gate pattern

Claude Code hooks block on **exit code 2** (exit 0 proceeds; the blocking message is fed back
to the session). That lets a _checker_ stop a _maker_ from proceeding on broken state.

## Shipped building blocks

| Hook                  | Event             | What it does                                                                                                                                                                    |
| --------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `spec-gate.sh`        | Stop              | Blocks (exit 2) when the Spec status ladder is violated (`docs/specs/check_spec_status.py`).                                                                                    |
| `commit-gate.sh`      | PreToolUse(Bash)  | Blocks `git commit` unless a quality gate validated **this exact tree** (diff-bound — any edit since the gate invalidates it; proven by the tree-hash `gate-track.sh` records). |
| `gate-track.sh`       | PostToolUse(Bash) | Records a passing quality gate (writes the validated **tree-hash** `commit-gate.sh` re-checks). Tune `GATE_RE`.                                                                 |
| `pre-bash-filter.sh`  | PreToolUse(Bash)  | Context hygiene — prepends `NO_COLOR=1` to keep ANSI codes out of context.                                                                                                      |
| `post-compact-log.sh` | PostCompact       | Measurement — logs compaction events to `.claude/storage/compaction.log` (the data that tells you whether context work pays off).                                               |

**Hook-authoring rule (encoded in `pre-bash-filter.sh`):** a mutation hook returns **only**
`updatedInput`, never a `permissionDecision: "allow"` — emitting "allow" would auto-approve
every call and bypass the permission allowlist.

## Enabling them (the STAGED convention)

`STAGED.example.json` holds all the wiring **dormant** in one labeled file (more discoverable
than inert scripts you have to find). To enable a gate, copy the block(s) you want into the
`hooks` object of **your repo's** `.claude/settings.json` — not the plugin, so `/plugin update`
keeps working. `${CLAUDE_PLUGIN_ROOT}` resolves to the installed plugin. Example (the spec gate):

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/spec-gate.sh"
          }
        ]
      }
    ]
  }
}
```

⚠️ **autoUpdate caveat (#52218):** bundled hook changes don't propagate via autoUpdate — after
a plugin update that changes a hook, run `/plugin update`. Because the wiring lives in _your_
settings, you control when each gate is active.

For a heavier gate, point a hook at a headless `audit-harness` run — same pattern, broader
coverage, slower.

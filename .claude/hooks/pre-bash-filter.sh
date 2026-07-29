#!/usr/bin/env bash
# PreToolUse(Bash): context-hygiene hook — suppress ANSI color to keep escape codes
# out of the context window. Prepends NO_COLOR=1 to every Bash command (widely
# supported; shell state doesn't persist between tool calls, so it's safe).
#
# IMPORTANT (hook-authoring rule): returns ONLY updatedInput, NEVER a
# permissionDecision. Emitting "allow" here would auto-approve every Bash call and
# bypass the permission allowlist. Omitting it lets the normal permission flow run.
#
# Ships inert — wire it from your repo's .claude/settings.json (see hooks/README.md).

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$COMMAND" ] && exit 0
echo "$COMMAND" | grep -q 'NO_COLOR' && exit 0

jq -n --arg cmd "export NO_COLOR=1; $COMMAND" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": { "command": $cmd }
  }
}'
exit 0

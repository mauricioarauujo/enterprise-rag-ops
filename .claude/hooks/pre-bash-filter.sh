#!/bin/bash
# PreToolUse: Suppress color output to reduce ANSI noise in context.
# Prepends NO_COLOR=1 to all Bash commands — widely supported env var.
# Safe: shell state doesn't persist between tool calls.
# IMPORTANT: returns ONLY updatedInput, never permissionDecision. Setting
# "allow" here would auto-approve every Bash call and bypass the allowlist
# (a Bash(*) wildcard). Omitting it lets the normal permission flow run.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$COMMAND" ] && exit 0

# Skip if NO_COLOR already set
echo "$COMMAND" | grep -q 'NO_COLOR' && exit 0

jq -n --arg cmd "export NO_COLOR=1; $COMMAND" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": $cmd
    }
  }
}'

exit 0

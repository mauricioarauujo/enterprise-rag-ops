#!/bin/bash
# PreToolUse: Suppress color output to reduce ANSI noise in context.
# Prepends NO_COLOR=1 to all Bash commands — widely supported env var.
# Safe: shell state doesn't persist between tool calls.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$COMMAND" ] && exit 0

# Skip if NO_COLOR already set
echo "$COMMAND" | grep -q 'NO_COLOR' && exit 0

jq -n --arg cmd "export NO_COLOR=1; $COMMAND" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {
      "command": $cmd
    }
  }
}'

exit 0

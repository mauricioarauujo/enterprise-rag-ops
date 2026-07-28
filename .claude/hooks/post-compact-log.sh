#!/usr/bin/env bash
# PostCompact: log compaction events — the MEASUREMENT arm of self-improvement.
# Tracks frequency + type (manual/auto) + session so you can tell whether
# context-optimization work is actually paying off. Ships inert (see hooks/README.md).

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
REASON=$(echo "$INPUT" | jq -r '.hook_trigger_reason // "unknown"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/storage"
mkdir -p "$LOG_DIR"
echo "$TIMESTAMP | $REASON | session=$SESSION_ID" >> "$LOG_DIR/compaction.log"
exit 0

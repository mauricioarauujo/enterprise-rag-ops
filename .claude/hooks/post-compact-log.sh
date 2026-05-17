#!/bin/bash
# PostCompact: Log compaction events for measuring optimization impact.
# Tracks frequency, type (manual/auto), and session to detect regression.

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
REASON=$(echo "$INPUT" | jq -r '.hook_trigger_reason // "unknown"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/storage"
mkdir -p "$LOG_DIR"

echo "$TIMESTAMP | $REASON | session=$SESSION_ID" >> "$LOG_DIR/compaction.log"

exit 0

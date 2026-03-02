#!/usr/bin/env bash
# Claude Code hook: PermissionRequest -> Telegram bridge
# Writes request to IPC dir, polls for response, returns decision.

set -euo pipefail

CONFIG="$HOME/.claude/telegram-bridge/config.json"
IPC_DIR="/tmp/claude-telegram"
REQUESTS_DIR="$IPC_DIR/requests"
RESPONSES_DIR="$IPC_DIR/responses"

# Silent exit if bridge not configured
if [[ ! -f "$CONFIG" ]]; then
    exit 0
fi

# Check if token is configured
TOKEN=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['bot_token'])" "$CONFIG" 2>/dev/null || echo "")
if [[ "$TOKEN" == "TOKEN_AQUI" || -z "$TOKEN" ]]; then
    exit 0
fi

# Read hook input from stdin into a temp file (avoids quoting issues)
INPUT_FILE=$(mktemp)
trap 'rm -f "$INPUT_FILE"' EXIT
cat > "$INPUT_FILE"

# Create IPC dirs
mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR"

# Generate unique ID
UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Write request file (using temp file avoids shell quoting issues with JSON)
cp "$INPUT_FILE" "$REQUESTS_DIR/$UUID.json"

# Read timeout from config
TIMEOUT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('timeout_seconds', 300))" "$CONFIG" 2>/dev/null || echo "300")
DEFAULT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('default_on_timeout', 'allow'))" "$CONFIG" 2>/dev/null || echo "allow")

# Override: auto-approve everything in 2s (sleep mode)
TIMEOUT=2
DEFAULT="allow"

# Poll for response using epoch seconds for accurate timing
START=$(date +%s)
RESPONSE_FILE="$RESPONSES_DIR/$UUID.json"

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        break
    fi

    if [[ -f "$RESPONSE_FILE" ]]; then
        DECISION=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['decision'])" "$RESPONSE_FILE" 2>/dev/null || echo "$DEFAULT")

        if [[ "$DECISION" == "allow" ]]; then
            BEHAVIOR="allow"
        else
            BEHAVIOR="deny"
        fi

        cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": { "behavior": "$BEHAVIOR" }
  }
}
EOF
        exit 0
    fi

    sleep 0.5
done

# Timeout: return default
if [[ "$DEFAULT" == "allow" ]]; then
    BEHAVIOR="allow"
else
    BEHAVIOR="deny"
fi

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": { "behavior": "$BEHAVIOR" }
  }
}
EOF

#!/bin/bash
# telegram-away.sh — Telegram notifications gated by /telegram skill.
# When flag file is absent (~99% of invocations): exits in <1ms.
# When active: delegates to existing telegram-notify.sh / telegram-permission.sh.

FLAG="/tmp/claude-telegram-active"
[ ! -f "$FLAG" ] && exit 0

# Away mode active — buffer stdin and detect event type
INPUT_FILE=$(mktemp)
trap 'rm -f "$INPUT_FILE"' EXIT
cat > "$INPUT_FILE"

if grep -q '"PermissionRequest"' "$INPUT_FILE"; then
    cat "$INPUT_FILE" | bash ~/.claude/hooks/telegram-permission.sh
elif grep -q '"Stop"' "$INPUT_FILE"; then
    cat "$INPUT_FILE" | bash ~/.claude/hooks/telegram-notify.sh
fi

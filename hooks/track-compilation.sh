#!/bin/bash
# Hooks E+F: PostToolUse Bash — track compilation failures, escalate after 3
# Cost: ~20 tokens normally, ~150 tokens on escalation

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "default"')

# Only process compilation commands
IS_COMPILE=0
case "$COMMAND" in
  *"lake build"*|*"lake env lean"*) IS_COMPILE=1 ;;
  *"cargo build"*|*"cargo test"*|*"cargo check"*) IS_COMPILE=1 ;;
  *"pytest"*|*"python -m pytest"*|*"python3 -m pytest"*) IS_COMPILE=1 ;;
  *"make"*|*"gcc "*|*"clang "*|*"g++ "*) IS_COMPILE=1 ;;
esac

if [ "$IS_COMPILE" = "0" ]; then
  exit 0
fi

# Check if compilation succeeded or failed by examining stderr/stdout for error patterns
TOOL_STDERR=$(echo "$INPUT" | jq -r '.tool_response.stderr // empty')
TOOL_STDOUT=$(echo "$INPUT" | jq -r '.tool_response.stdout // empty')
EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exit_code // empty')

# Determine success/failure
FAILED=0
if [ "$EXIT_CODE" != "" ] && [ "$EXIT_CODE" != "0" ] && [ "$EXIT_CODE" != "null" ]; then
  FAILED=1
fi
# Also check for error patterns in output (some tools don't set exit code)
if echo "$TOOL_STDERR$TOOL_STDOUT" | grep -qiE "(error|failed|FAILED|unknown identifier|type mismatch|sorry|declaration uses)"; then
  FAILED=1
fi

# Counter file per session
COUNTER_FILE="/tmp/claude_compile_fails_$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9')"

if [ "$FAILED" = "1" ]; then
  # Increment failure counter
  COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
  COUNT=$((COUNT + 1))
  echo "$COUNT" > "$COUNTER_FILE"

  if [ "$COUNT" -ge 3 ]; then
    cat >&2 <<EOF
ESCALACION: $COUNT fallos de compilacion consecutivos en esta sesion.
Protocolo de escalacion (OBLIGATORIO):
1. Ejecutar: python3 ~/.claude/skills/ask-dojo/scripts/lean_search.py --state "{goal_actual}"
2. Ejecutar: python3 ~/.claude/skills/ask-lean/scripts/ask_lean.py --rounds 2 --context "He fallado $COUNT veces" "{descripcion_del_problema}"
3. Si persiste: reformular el enunciado (cambiar signatura, agregar hipotesis)
NO seguir intentando lo mismo. Cambiar de estrategia.
EOF
  fi
else
  # Hook F: Success — reset counter
  if [ -f "$COUNTER_FILE" ]; then
    rm -f "$COUNTER_FILE"
  fi
  # Reset edit counter (Hook H coordination)
  EDIT_COUNTER="/tmp/claude_edit_count_$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9')"
  if [ -f "$EDIT_COUNTER" ]; then
    echo "0" > "$EDIT_COUNTER"
  fi
fi

exit 0

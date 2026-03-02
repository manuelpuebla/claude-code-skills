#!/bin/bash
# Hook H: PostToolUse Edit — warn after 3 edits without compilation
# Cost: ~15ms, ~80 tokens when triggered
# Coordination: track-compilation.sh (Hook F) resets this counter on successful compile

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "default"')

# Only process source files
EXT="${FILE_PATH##*.}"
case "$EXT" in
  lean|rs|py|c|cpp|h|hpp|go) ;;
  *) exit 0 ;;
esac

# Increment edit counter
COUNTER_FILE="/tmp/claude_edit_count_$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9')"
COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

# Warn every 3 edits without compilation
if [ "$((COUNT % 3))" = "0" ]; then
  # Detect project type for correct compile command
  PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || dirname "$FILE_PATH")

  COMPILE_CMD="make"
  if [ -f "$PROJECT_DIR/lakefile.lean" ] || [ -f "$PROJECT_DIR/lakefile.toml" ]; then
    COMPILE_CMD="lake build"
  elif [ -f "$PROJECT_DIR/Cargo.toml" ]; then
    COMPILE_CMD="cargo check"
  elif [ -f "$PROJECT_DIR/pyproject.toml" ] || [ -f "$PROJECT_DIR/setup.py" ]; then
    COMPILE_CMD="pytest"
  fi

  cat >&2 <<EOF
COMPILA AHORA: $COUNT edits consecutivos sin compilar.
Ejecuta: $COMPILE_CMD
Regla: no acumular mas de 3 cambios sin verificar contra el compilador.
Si hay regresion, revertir al ultimo estado bueno ANTES de diagnosticar.
EOF
fi

exit 0

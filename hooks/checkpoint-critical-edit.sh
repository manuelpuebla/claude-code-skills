#!/bin/bash
# Hook G: PreToolUse Edit — warn when editing critical/foundational files
# Cost: ~50ms normally, ~80ms with fan-out check

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "default"')

# Only process source files
EXT="${FILE_PATH##*.}"
case "$EXT" in
  lean|rs|py|c|cpp|h|hpp|go) ;;
  *) exit 0 ;;
esac

# Skip if file doesn't exist
if [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# Check if in git repo
PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")" && git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$PROJECT_DIR" ]; then
  exit 0
fi

# --- Firewall check for Lean files (fan-out heuristic) ---
if [ "$EXT" = "lean" ]; then
  BASENAME=$(basename "$FILE_PATH" .lean)
  # Count files that import this module (limit search for speed)
  IMPORT_COUNT=$(grep -rl --include="*.lean" "import.*$BASENAME" "$PROJECT_DIR" 2>/dev/null | head -10 | grep -v "$FILE_PATH" | wc -l | tr -d ' ')

  if [ "$IMPORT_COUNT" -ge 3 ]; then
    # Check if the new code uses _aux pattern (firewall)
    NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')

    if ! echo "$NEW_STRING" | grep -q "_aux"; then
      cat >&2 <<EOF
FIREWALL: $(basename "$FILE_PATH") es importado por $IMPORT_COUNT+ archivos (alto fan-out).
Protocolo obligatorio para nodos fundacionales:
1. Crear theorem/def {nombre}_aux con signatura flexible
2. Probar _aux sin tocar el original
3. Solo migrar cuando _aux compile sin sorry
Si ya estas usando _aux, ignora este aviso.
EOF
    fi
  fi
fi

# --- Checkpoint: warn if dirty working tree before editing new file ---
DIRTY_OTHER=$(cd "$PROJECT_DIR" && git diff --name-only 2>/dev/null | grep -v "$(basename "$FILE_PATH")" | head -3)
if [ -n "$DIRTY_OTHER" ]; then
  DIRTY_COUNT=$(echo "$DIRTY_OTHER" | wc -l | tr -d ' ')
  # Only warn once per file per session (avoid repetitive warnings)
  WARN_KEY=$(echo "$FILE_PATH" | tr '/' '_')
  MARKER_FILE="/tmp/claude_checkpoint_$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9')"

  if ! grep -q "$WARN_KEY" "$MARKER_FILE" 2>/dev/null; then
    echo "$WARN_KEY" >> "$MARKER_FILE"
    cat >&2 <<EOF
CHECKPOINT: $DIRTY_COUNT archivo(s) con cambios sin commit antes de editar $(basename "$FILE_PATH").
Considera: git add -A && git commit -m "checkpoint antes de $(basename "$FILE_PATH")"
EOF
  fi
fi

exit 0

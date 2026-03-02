#!/bin/bash
# Hook C: PreToolUse Read — warn if reading large source file without offset
# Cost: ~50 tokens when triggered, ~10ms execution

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty')

# Skip if offset is specified (already reading a section)
if [ -n "$OFFSET" ] && [ "$OFFSET" != "null" ] && [ "$OFFSET" != "0" ]; then
  exit 0
fi

# Skip if file doesn't exist
if [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# Only warn for source files
EXT="${FILE_PATH##*.}"
case "$EXT" in
  lean|rs|py|c|cpp|h|hpp|go|java|ts|js|md) ;;
  *) exit 0 ;;
esac

FILE_LINES=$(wc -l < "$FILE_PATH" 2>/dev/null | tr -d ' ')

# Block if >200 lines without offset
if [ "$FILE_LINES" -gt 200 ] 2>/dev/null; then
  cat >&2 <<EOF
BLOQUEADO: Archivo source de $FILE_LINES lineas sin offset.
Usa scout.py para obtener un Code Map compacto (~3K tokens vs ~${FILE_LINES} lineas):
  python3 ~/.claude/skills/plan-project/scripts/scout.py "$FILE_PATH"
Luego usa Read con offset+limit para leer solo la seccion relevante.
EOF
  exit 1
fi

exit 0

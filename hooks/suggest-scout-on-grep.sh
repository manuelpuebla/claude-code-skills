#!/bin/bash
# Hook D: PreToolUse Grep — suggest scout.py when searching source files
# Cost: ~80 tokens when triggered, ~10ms execution

INPUT=$(cat)
SEARCH_PATH=$(echo "$INPUT" | jq -r '.tool_input.path // empty')
GLOB_FILTER=$(echo "$INPUT" | jq -r '.tool_input.glob // empty')
TYPE_FILTER=$(echo "$INPUT" | jq -r '.tool_input.type // empty')

# Detect if searching source code files
IS_SOURCE=0

# Check by type filter
case "$TYPE_FILTER" in
  lean|rust|py|python|c|cpp|go|java|js|ts) IS_SOURCE=1 ;;
esac

# Check by glob filter
case "$GLOB_FILTER" in
  *.lean|*.rs|*.py|*.c|*.cpp|*.h|*.go|*.java|*.ts|*.js) IS_SOURCE=1 ;;
esac

# Check if path points to a source directory (heuristic)
if [ -n "$SEARCH_PATH" ] && [ -d "$SEARCH_PATH" ]; then
  # Check if directory contains source files
  SOURCE_COUNT=$(find "$SEARCH_PATH" -maxdepth 2 \( -name "*.lean" -o -name "*.rs" -o -name "*.py" -o -name "*.c" \) 2>/dev/null | head -5 | wc -l | tr -d ' ')
  if [ "$SOURCE_COUNT" -gt 0 ]; then
    IS_SOURCE=1
  fi
fi

if [ "$IS_SOURCE" = "1" ]; then
  cat >&2 <<EOF
TIP: Si buscas estructura de codigo (declaraciones, funciones, sorry, TODO), scout.py es mas eficiente:
  python3 ~/.claude/skills/plan-project/scripts/scout.py --pending-only "$SEARCH_PATH"
  python3 ~/.claude/skills/plan-project/scripts/scout.py --targets "nombre" "$SEARCH_PATH"
El Code Map indexa todas las declaraciones con lineas, signaturas y dependencias.
EOF
fi

exit 0

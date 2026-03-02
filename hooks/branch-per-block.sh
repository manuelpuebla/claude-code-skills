#!/bin/bash
# Hook I: PreToolUse Edit — suggest creating work branch before first edit
# Cost: ~40ms, ~50 tokens when triggered (once per session)

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "default"')

# Only process source files
EXT="${FILE_PATH##*.}"
case "$EXT" in
  lean|rs|py|c|cpp|h|hpp|go) ;;
  *) exit 0 ;;
esac

# Check if in git repo
PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$PROJECT_DIR" ]; then
  exit 0
fi

# Check current branch
CURRENT_BRANCH=$(cd "$PROJECT_DIR" && git branch --show-current 2>/dev/null)

# If already on a bloque-* or block-* branch, nothing to do
case "$CURRENT_BRANCH" in
  bloque-*|block-*) exit 0 ;;
esac

# Only suggest once per session (marker file)
MARKER_FILE="/tmp/claude_branch_suggested_$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9')"
if [ -f "$MARKER_FILE" ]; then
  exit 0
fi
touch "$MARKER_FILE"

# Find next block number based on existing branches
BLOCK_NUM=$(cd "$PROJECT_DIR" && git branch --list "bloque-*" 2>/dev/null | wc -l | tr -d ' ')
BLOCK_NUM=$((BLOCK_NUM + 1))

cat >&2 <<EOF
BRANCH DE SEGURIDAD: Estas en '$CURRENT_BRANCH' y vas a editar codigo source.
Crea una branch de trabajo para rollback seguro:
  cd "$PROJECT_DIR" && git add -A && git commit -m "checkpoint pre-bloque-$BLOCK_NUM" && git checkout -b bloque-$BLOCK_NUM
Si algo sale mal, puedes volver con: git checkout $CURRENT_BRANCH
EOF

exit 0

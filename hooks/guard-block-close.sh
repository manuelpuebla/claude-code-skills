#!/bin/bash
# Hook: PreToolUse Edit — Guard against marking nodes ✓ without running close_block.py
# Triggers when ARCHITECTURE.md is edited to add ✓ markers.
# Cost: ~30ms (fast path: file not ARCHITECTURE.md)

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only trigger for ARCHITECTURE.md
BASENAME=$(basename "$FILE_PATH" 2>/dev/null)
if [ "$BASENAME" != "ARCHITECTURE.md" ]; then
  exit 0
fi

# Check if the edit adds ✓ checkmarks (completion markers)
NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')

if ! echo "$NEW_STRING" | grep -q "✓"; then
  exit 0
fi

# Check if close_block.py was run recently
PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$PROJECT_DIR" ]; then
  PROJECT_DIR=$(dirname "$FILE_PATH")
fi

PROJECT_SLUG=$(basename "$PROJECT_DIR" | tr ' ' '_')
MARKER_FILE="/tmp/claude_block_verified_${PROJECT_SLUG}"

if [ ! -f "$MARKER_FILE" ]; then
  cat >&2 <<EOF
BLOQUEO: Estás marcando nodos como ✓ en ARCHITECTURE.md sin haber ejecutado close_block.py.

Protocolo obligatorio ANTES de marcar ✓:
  1. python3 ~/.claude/skills/plan-project/scripts/close_block.py \\
       --project "$PROJECT_DIR" --block "Bloque N" \\
       --nodes '{"nodo": ["archivo.lean"]}'
  2. Si close_block.py PASS → lanzar QA riguroso (collab.py)
  3. Si QA PASS → registrar en BENCHMARKS.md → ENTONCES marcar ✓ aquí

NUNCA marcar ✓ sin verificación mecánica + QA.
EOF
  exit 0
fi

# Check if the LAST verification passed
LAST_ENTRY=$(tail -1 "$MARKER_FILE")
LAST_PASS=$(echo "$LAST_ENTRY" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('pass', False))" 2>/dev/null)

if [ "$LAST_PASS" != "True" ]; then
  LAST_BLOCK=$(echo "$LAST_ENTRY" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('block', '?'))" 2>/dev/null)
  cat >&2 <<EOF
BLOQUEO: La última ejecución de close_block.py ($LAST_BLOCK) terminó en FAIL.
Resuelve los problemas y re-ejecuta close_block.py antes de marcar ✓.
EOF
  exit 0
fi

exit 0

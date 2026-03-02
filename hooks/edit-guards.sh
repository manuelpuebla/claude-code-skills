#!/bin/bash
# edit-guards.sh — Unified PreToolUse Edit hook.
# Replaces 3 separate hooks (checkpoint-critical-edit, branch-per-block,
# guard-block-close) with a single shell invocation: one jq parse, one
# git rev-parse, cached grep for Lean fan-out.

set -euo pipefail

# ── Parse input once ──
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "default"')
SESSION_SAFE=$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9')
BASENAME=$(basename "$FILE_PATH" 2>/dev/null || true)

# ══════════════════════════════════════════════════════════════════════
# Guard A: ARCHITECTURE.md ✓ check (from guard-block-close.sh)
# ══════════════════════════════════════════════════════════════════════
if [ "$BASENAME" = "ARCHITECTURE.md" ]; then
  NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
  if echo "$NEW_STRING" | grep -q "✓"; then
    PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || dirname "$FILE_PATH")
    PROJECT_SLUG=$(basename "$PROJECT_DIR" | tr ' ' '_')
    MARKER="/tmp/claude_block_verified_${PROJECT_SLUG}"
    if [ ! -f "$MARKER" ]; then
      cat >&2 <<'EOF'
BLOQUEO: Marcando nodos ✓ en ARCHITECTURE.md sin close_block.py.
Protocolo: close_block.py → QA → BENCHMARKS.md → marcar ✓
EOF
    else
      LAST_PASS=$(tail -1 "$MARKER" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('pass', False))" 2>/dev/null || echo "False")
      if [ "$LAST_PASS" != "True" ]; then
        echo "BLOQUEO: close_block.py terminó en FAIL. Resolver antes de marcar ✓." >&2
      fi
    fi
  fi
  exit 0  # ARCHITECTURE.md is never source — skip remaining guards
fi

# ══════════════════════════════════════════════════════════════════════
# Only source files from here
# ══════════════════════════════════════════════════════════════════════
EXT="${FILE_PATH##*.}"
case "$EXT" in
  lean|rs|py|c|cpp|h|hpp|go) ;;
  *) exit 0 ;;
esac

# Single git rev-parse shared by all guards below
PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || true)
[ -z "$PROJECT_DIR" ] && exit 0

# ══════════════════════════════════════════════════════════════════════
# Guard B: Branch suggestion (once per session, from branch-per-block.sh)
# ══════════════════════════════════════════════════════════════════════
BRANCH_MARKER="/tmp/claude_branch_suggested_${SESSION_SAFE}"
if [ ! -f "$BRANCH_MARKER" ]; then
  CURRENT_BRANCH=$(cd "$PROJECT_DIR" && git branch --show-current 2>/dev/null || true)
  case "$CURRENT_BRANCH" in
    bloque-*|block-*) ;;
    *)
      touch "$BRANCH_MARKER"
      BLOCK_NUM=$(cd "$PROJECT_DIR" && git branch --list "bloque-*" 2>/dev/null | wc -l | tr -d ' ')
      BLOCK_NUM=$((BLOCK_NUM + 1))
      cat >&2 <<EOF
BRANCH: En '$CURRENT_BRANCH'. Crear branch de trabajo:
  cd "$PROJECT_DIR" && git add -A && git commit -m "checkpoint pre-bloque-$BLOCK_NUM" && git checkout -b bloque-$BLOCK_NUM
EOF
      ;;
  esac
fi

# ══════════════════════════════════════════════════════════════════════
# Guard C: Lean firewall with CACHED grep (from checkpoint-critical-edit.sh)
# Cache persists per file per session — grep runs once, not on every edit.
# ══════════════════════════════════════════════════════════════════════
if [ "$EXT" = "lean" ]; then
  LEAN_BASENAME=$(basename "$FILE_PATH" .lean)
  CACHE_FILE="/tmp/claude_fanout_${SESSION_SAFE}_${LEAN_BASENAME}"

  if [ -f "$CACHE_FILE" ]; then
    IMPORT_COUNT=$(cat "$CACHE_FILE")
  else
    IMPORT_COUNT=$(grep -rl --include="*.lean" "import.*${LEAN_BASENAME}" "$PROJECT_DIR" 2>/dev/null | grep -v "$FILE_PATH" | head -10 | wc -l | tr -d ' ')
    echo "$IMPORT_COUNT" > "$CACHE_FILE"
  fi

  if [ "$IMPORT_COUNT" -ge 3 ]; then
    NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
    if ! echo "$NEW_STRING" | grep -q "_aux"; then
      cat >&2 <<EOF
FIREWALL: $(basename "$FILE_PATH") importado por ${IMPORT_COUNT}+ archivos.
Usar patrón _aux: crear {nombre}_aux, probar, migrar cuando compile.
EOF
    fi
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# Guard D: Dirty tree warning (once per file per session)
# ══════════════════════════════════════════════════════════════════════
WARN_KEY=$(echo "$FILE_PATH" | tr '/' '_')
DIRTY_MARKER="/tmp/claude_checkpoint_${SESSION_SAFE}"

if ! grep -q "$WARN_KEY" "$DIRTY_MARKER" 2>/dev/null; then
  DIRTY_OTHER=$(cd "$PROJECT_DIR" && git diff --name-only 2>/dev/null | grep -v "$(basename "$FILE_PATH")" | head -3)
  if [ -n "$DIRTY_OTHER" ]; then
    DIRTY_COUNT=$(echo "$DIRTY_OTHER" | wc -l | tr -d ' ')
    echo "$WARN_KEY" >> "$DIRTY_MARKER"
    echo "CHECKPOINT: $DIRTY_COUNT archivo(s) sin commit antes de editar $(basename "$FILE_PATH")." >&2
  fi
fi

exit 0

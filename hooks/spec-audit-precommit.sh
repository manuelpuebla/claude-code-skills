#!/bin/bash
# Hook: PreToolUse Bash — advisory spec audit before git commit
# Checks staged .lean files for T1 vacuity and T1.5 identity passes.
# Advisory only: emits WARNING but does NOT block the commit.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only trigger on git commit commands
if ! echo "$COMMAND" | grep -qE 'git\s+commit'; then
  exit 0
fi

# Detect project root from working directory
PROJECT_ROOT=$(pwd)
if [ ! -f "$PROJECT_ROOT/lakefile.toml" ] && [ ! -f "$PROJECT_ROOT/lakefile.lean" ]; then
  # Not a Lean project
  exit 0
fi

# Check if there are staged .lean files
STAGED_LEAN=$(git diff --cached --name-only 2>/dev/null | grep '\.lean$' || true)
if [ -z "$STAGED_LEAN" ]; then
  exit 0
fi

# Run spec audit (pipeline-only, JSON, fast mode — no --deep)
SPEC_AUDIT="$HOME/.claude/skills/plan-project/scripts/spec_audit.py"
if [ ! -f "$SPEC_AUDIT" ]; then
  exit 0
fi

RESULT=$(python3 "$SPEC_AUDIT" --project "$PROJECT_ROOT" --pipeline-only --json 2>/dev/null)
if [ $? -ne 0 ] && [ -z "$RESULT" ]; then
  exit 0  # Script error, don't block
fi

T1=$(echo "$RESULT" | jq -r '.tier1_issues // 0')
T15=$(echo "$RESULT" | jq -r '.tier15_issues // 0')

if [ "$T1" -gt 0 ] 2>/dev/null || [ "$T15" -gt 0 ] 2>/dev/null; then
  cat >&2 <<EOF
[spec-audit] WARNING: Spec issues detected in staged .lean files
  T1 (vacuity): $T1
  T1.5 (identity passes): $T15
  Consider running: python3 $SPEC_AUDIT --project $PROJECT_ROOT
  This is advisory — commit will proceed.
EOF
fi

# Always exit 0 — advisory only, never blocks
exit 0

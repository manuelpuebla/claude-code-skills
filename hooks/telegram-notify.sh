#!/usr/bin/env bash
# Claude Code hook: Fire-and-forget notifications to Telegram bridge
# Handles PostToolUse/Bash (compilation errors + activity log) and Stop (task complete with summary).

set -euo pipefail

CONFIG="$HOME/.claude/telegram-bridge/config.json"
IPC_DIR="/tmp/claude-telegram"
NOTIFY_DIR="$IPC_DIR/notify"
ACTIVITY_DIR="$IPC_DIR/activity"

# Silent exit if bridge not configured
if [[ ! -f "$CONFIG" ]]; then
    exit 0
fi

TOKEN=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['bot_token'])" "$CONFIG" 2>/dev/null || echo "")
if [[ "$TOKEN" == "TOKEN_AQUI" || -z "$TOKEN" ]]; then
    exit 0
fi

# Read hook input from stdin into temp file
INPUT_FILE=$(mktemp)
trap 'rm -f "$INPUT_FILE"' EXIT
cat > "$INPUT_FILE"

mkdir -p "$NOTIFY_DIR" "$ACTIVITY_DIR"

UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Use python to parse and decide what to notify
python3 << 'PYEOF' - "$INPUT_FILE" "$NOTIFY_DIR/$UUID.json" "$CONFIG" "$ACTIVITY_DIR"
import json
import sys
import os
from pathlib import Path

input_file = sys.argv[1]
output_file = sys.argv[2]
config_file = sys.argv[3]
activity_dir = Path(sys.argv[4])

with open(input_file) as f:
    data = json.load(f)

with open(config_file) as f:
    config = json.load(f)

hook_event = data.get("hook_event_name", "")
session_id = data.get("session_id", "")
cwd = data.get("cwd", "")

# --- Activity log helpers ---
def get_activity_file(sid):
    """One log file per session."""
    if not sid:
        return None
    safe = sid.replace("/", "_")[:40]
    return activity_dir / f"{safe}.log"

def append_activity(sid, entry):
    """Append a JSON object as one line."""
    af = get_activity_file(sid)
    if af:
        with open(af, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def read_activity_summary(sid, max_lines=10):
    af = get_activity_file(sid)
    if not af or not af.exists():
        return []
    entries = []
    for line in af.read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries[-max_lines:]

def clear_activity(sid):
    af = get_activity_file(sid)
    if af and af.exists():
        af.unlink()

# --- Handle Stop event ---
if hook_event == "Stop":
    if not config.get("notify_task_completion", True):
        sys.exit(0)

    summary = read_activity_summary(session_id)
    clear_activity(session_id)

    notification = {
        "event": "task_complete",
        "session_id": session_id,
        "cwd": cwd,
        "activity_summary": summary,
    }
    with open(output_file, "w") as f:
        json.dump(notification, f)
    sys.exit(0)

# --- Handle PostToolUse for Bash ---
tool_name = data.get("tool_name", "")
if tool_name != "Bash":
    sys.exit(0)

tool_result = data.get("tool_result", {})
tool_input = data.get("tool_input", {})

# Extract command and exit code
exit_code = None
stderr = ""
stdout = ""
if isinstance(tool_result, dict):
    exit_code = tool_result.get("exit_code", tool_result.get("exitCode"))
    stderr = tool_result.get("stderr", "")
    stdout = tool_result.get("stdout", "")
elif isinstance(tool_result, str):
    stderr = tool_result

command = ""
if isinstance(tool_input, dict):
    command = tool_input.get("command", "")
elif isinstance(tool_input, str):
    command = tool_input

# Always log activity (regardless of success/failure)
if command and session_id:
    append_activity(session_id, {
        "cmd": command[:200],
        "exit": exit_code,
        "ok": exit_code == 0,
    })

# Only send Telegram notification on compilation errors
if not config.get("notify_compilation_errors", True):
    sys.exit(0)

BUILD_COMMANDS = ["lake build", "cargo build", "cargo test", "pytest", "make",
                  "npm run build", "npm test", "go build", "go test",
                  "lean", "leanc", "gcc", "g++", "clang", "rustc", "javac"]

is_build = any(bc in command for bc in BUILD_COMMANDS)
is_failure = exit_code is not None and exit_code != 0

if not (is_build and is_failure):
    sys.exit(0)

error_text = stderr if stderr else stdout
if len(error_text) > 500:
    error_text = error_text[:500] + "..."

notification = {
    "event": "compilation_error",
    "session_id": session_id,
    "cwd": cwd,
    "command": command[:200],
    "exit_code": exit_code,
    "stderr": error_text,
}

with open(output_file, "w") as f:
    json.dump(notification, f)

PYEOF

#!/usr/bin/env bash
# stop-server.sh: stops the Alfred visual server.
#
# Usage:
#   stop-server.sh <session_dir>
#
# Reads the PID from <session_dir>/state/server.pid, sends SIGTERM and waits
# up to 2 s. If the process does not exit, sends SIGKILL. Removes the state
# files and deletes the session directory if it is under /tmp.
#
# JSON output on stdout:
#   {"status":"stopped"}          - The server stopped correctly.
#   {"status":"not_running"}      - No active server in that directory.
#   {"status":"failed","error":"..."} - The process could not be stopped.

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
  printf '{"status":"failed","error":"Использование: stop-server.sh <session_dir>"}\n'
  exit 1
fi

SESSION_DIR="$1"

if [[ ! -d "$SESSION_DIR" ]]; then
  printf '{"status":"not_running"}\n'
  exit 0
fi

PID_FILE="${SESSION_DIR}/state/server.pid"
LOG_FILE="${SESSION_DIR}/state/server.log"
SERVER_INFO_FILE="${SESSION_DIR}/state/server-info"

# ---------------------------------------------------------------------------
# Check for a recorded PID
# ---------------------------------------------------------------------------

if [[ ! -f "$PID_FILE" ]]; then
  printf '{"status":"not_running"}\n'
  exit 0
fi

SERVER_PID="$(cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]')"

if [[ -z "$SERVER_PID" ]]; then
  rm -f "$PID_FILE"
  printf '{"status":"not_running"}\n'
  exit 0
fi

REAL_SESSION_DIR="$(cd "$SESSION_DIR" 2>/dev/null && pwd -P || echo "$SESSION_DIR")"

get_process_command() {
  local pid="$1"
  ps eww -p "$pid" -o command= 2>/dev/null || ps -p "$pid" -o command= 2>/dev/null || true
}

is_expected_visual_process() {
  local pid="$1"
  local command_line
  local server_info_pid=""
  local server_info_session=""
  command_line="$(get_process_command "$pid")"
  [[ -n "$command_line" ]] || return 1
  [[ "$command_line" == *"server.cjs"* ]] || return 1

  if [[ "$command_line" == *"ALFRED_VISUAL_DIR=$REAL_SESSION_DIR"* ]]; then
    return 0
  fi

  if [[ -f "$SERVER_INFO_FILE" ]]; then
    server_info_pid="$(python3 - <<'PY' "$SERVER_INFO_FILE"
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print("")
else:
    print(data.get("server_pid", ""))
PY
)"
    server_info_session="$(python3 - <<'PY' "$SERVER_INFO_FILE"
import json, os, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print("")
else:
    value = data.get("session_dir", "")
    if value:
        print(os.path.realpath(value))
    else:
        print("")
PY
)"
  fi

  [[ "$server_info_pid" == "$pid" ]] || return 1
  [[ "$server_info_session" == "$REAL_SESSION_DIR" ]] || return 1
  return 0
}

# ---------------------------------------------------------------------------
# Check if the process is alive
# ---------------------------------------------------------------------------

if ! kill -0 "$SERVER_PID" 2>/dev/null || ! is_expected_visual_process "$SERVER_PID"; then
  # The process no longer exists. Clean up leftovers
  rm -f "$PID_FILE" "$LOG_FILE" "$SERVER_INFO_FILE"
  printf '{"status":"not_running"}\n'
  exit 0
fi

# ---------------------------------------------------------------------------
# Send SIGTERM and wait up to 2 s (poll every 0.1 s)
# ---------------------------------------------------------------------------

kill -TERM "$SERVER_PID" 2>/dev/null || true

_waited=0
while kill -0 "$SERVER_PID" 2>/dev/null && [[ $_waited -lt 20 ]]; do
  sleep 0.1
  (( _waited++ )) || true
done

# ---------------------------------------------------------------------------
# Fall back to SIGKILL if the process is still alive
# ---------------------------------------------------------------------------

if kill -0 "$SERVER_PID" 2>/dev/null; then
  kill -KILL "$SERVER_PID" 2>/dev/null || true

  # Wait one more second to confirm the exit
  _kill_waited=0
  while kill -0 "$SERVER_PID" 2>/dev/null && [[ $_kill_waited -lt 10 ]]; do
    sleep 0.1
    (( _kill_waited++ )) || true
  done

  # If it is still alive after SIGKILL, report the failure
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    printf '{"status":"failed","error":"Не удалось остановить процесс %s"}\n' "$SERVER_PID"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Remove the state files
# ---------------------------------------------------------------------------

rm -f "$PID_FILE" "$LOG_FILE"

# ---------------------------------------------------------------------------
# Delete the session directory only if it is under /tmp.
# Persistent directories (inside a project) stay so that the user
# can inspect the generated content.
# ---------------------------------------------------------------------------

# Normalize the real path to compare with /tmp safely
REAL_TMP="$(cd /tmp 2>/dev/null && pwd -P || echo "/tmp")"

if [[ "$REAL_SESSION_DIR" == "${REAL_TMP}/"* ]]; then
  rm -rf "$SESSION_DIR"
fi

printf '{"status":"stopped"}\n'

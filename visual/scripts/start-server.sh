#!/usr/bin/env bash
# start-server.sh: starts the Alfred visual server.
#
# Usage:
#   start-server.sh [--project-dir <path>] [--host <host>] [--url-host <host>]
#                   [--foreground | --background]
#
# In foreground mode the Node process runs directly (blocking).
# In background mode it starts with nohup + disown, and the script waits up
# to 5 s for the "server-started" line in the log.
#
# JSON output on stdout:
#   Success: {"type":"server-started","port":...,"url":"...","session_dir":"..."}
#   Error:   {"type":"error","message":"..."}

set -euo pipefail
umask 077

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

json_error() {
  local message="$1"
  printf '{"type":"error","message":"%s"}\n' "$(json_escape "$message")"
}

require_value() {
  local flag="$1"
  if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
    json_error "Нет значения для ${flag}"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

PROJECT_DIR=""
HOST="127.0.0.1"
URL_HOST=""
MODE=""          # foreground | background (resolved below)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      require_value "$1" "${2:-}"
      PROJECT_DIR="$2"
      shift 2
      ;;
    --host)
      require_value "$1" "${2:-}"
      HOST="$2"
      shift 2
      ;;
    --url-host)
      require_value "$1" "${2:-}"
      URL_HOST="$2"
      shift 2
      ;;
    --foreground)
      MODE="foreground"
      shift
      ;;
    --background)
      MODE="background"
      shift
      ;;
    *)
      json_error "Неизвестный аргумент: $1"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Detect environments that need foreground mode.
# Codex CI and Windows environments (MSYS/Cygwin) do not handle nohup + disown well.
# ---------------------------------------------------------------------------

if [[ -z "$MODE" ]]; then
  if [[ -n "${CODEX_CI:-}" ]]; then
    MODE="foreground"
  elif [[ "${MSYSTEM:-}" == MINGW* ]] || [[ "${MSYSTEM:-}" == MSYS* ]] || \
       [[ "${OSTYPE:-}" == cygwin* ]]; then
    MODE="foreground"
  else
    MODE="background"
  fi
fi

# ---------------------------------------------------------------------------
# Script directory: needed to find server.cjs
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_CJS="$SCRIPT_DIR/server.cjs"

if ! command -v node >/dev/null 2>&1; then
  json_error "Node.js не найден в PATH"
  exit 1
fi

if [[ ! -f "$SERVER_CJS" ]]; then
  json_error "Не найден server.cjs в $SCRIPT_DIR"
  exit 1
fi

# ---------------------------------------------------------------------------
# Resolve the owner PID (grandparent of the current process).
# Claude Code runs this script as a child. The real "owner" is the process
# that started Claude Code, that is, the grandparent (PPID of the PPID).
# ---------------------------------------------------------------------------

OWNER_PID=""
_ppid="$$"
_parent=""
_grandparent=""

# Try to get the PPID of the current process
_parent="$(ps -o ppid= -p "$_ppid" 2>/dev/null | tr -d ' ')" || true

if [[ -n "$_parent" && "$_parent" != "0" ]]; then
  _grandparent="$(ps -o ppid= -p "$_parent" 2>/dev/null | tr -d ' ')" || true
  if [[ -n "$_grandparent" && "$_grandparent" != "0" ]]; then
    OWNER_PID="$_grandparent"
  fi
fi

# ---------------------------------------------------------------------------
# Build the session directory
# ---------------------------------------------------------------------------

TIMESTAMP="$(date +%s)"

if [[ -n "$PROJECT_DIR" ]]; then
  # Persistent directory inside the project
  SESSION_DIR="${PROJECT_DIR}/.alfred-dev/visual/${$}-${TIMESTAMP}"
else
  # Temporary directory when there is no project
  SESSION_DIR="/tmp/alfred-visual-${$}-${TIMESTAMP}"
fi

# Create the subdirectories that server.cjs needs
mkdir -p "${SESSION_DIR}/content" "${SESSION_DIR}/state"

PID_FILE="${SESSION_DIR}/state/server.pid"
LOG_FILE="${SESSION_DIR}/state/server.log"

cleanup_failed_start() {
  rm -f "$PID_FILE"
}

# ---------------------------------------------------------------------------
# Kill the previous server if a PID file from an older session exists.
# This applies only when a fixed session directory is reused. In this
# script each session has a unique directory, but the logic stays in case
# an existing SESSION_DIR is passed in the future.
# ---------------------------------------------------------------------------

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    # Wait up to 2 s for it to exit
    _waited=0
    while kill -0 "$OLD_PID" 2>/dev/null && [[ $_waited -lt 20 ]]; do
      sleep 0.1
      (( _waited++ )) || true
    done
  fi
  rm -f "$PID_FILE"
fi

# ---------------------------------------------------------------------------
# Environment variables for the Node process
# ---------------------------------------------------------------------------

export ALFRED_VISUAL_DIR="$SESSION_DIR"
export ALFRED_VISUAL_HOST="$HOST"
if [[ -n "$URL_HOST" ]]; then
  export ALFRED_VISUAL_URL_HOST="$URL_HOST"
fi
if [[ -n "$OWNER_PID" ]]; then
  export ALFRED_VISUAL_OWNER_PID="$OWNER_PID"
fi

# ---------------------------------------------------------------------------
# Start in foreground mode (blocking)
# ---------------------------------------------------------------------------

if [[ "$MODE" == "foreground" ]]; then
  exec node "$SERVER_CJS"
fi

# ---------------------------------------------------------------------------
# Start in background mode
# ---------------------------------------------------------------------------

# Start the server and redirect stdout/stderr to the log
nohup node "$SERVER_CJS" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
disown "$SERVER_PID" 2>/dev/null || true

# Save the PID so that stop-server.sh can stop it
echo "$SERVER_PID" > "$PID_FILE"

# Wait up to 5 s for the server to write the "server-started" line
MAX_WAIT=50   # 50 iterations x 0.1 s = 5 s
_iter=0
SERVER_STARTED_LINE=""

while [[ $_iter -lt $MAX_WAIT ]]; do
  sleep 0.1
  (( _iter++ )) || true

  # Check that the process is still alive
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    ERROR_LOG="$(cat "$LOG_FILE" 2>/dev/null || echo "")"
    cleanup_failed_start
    printf '{"type":"error","message":"Процесс сервера неожиданно завершился","session_dir":"%s","log":%s}\n' \
      "$SESSION_DIR" \
      "$(printf '%s' "$ERROR_LOG" | node -e 'let d="";process.stdin.on("data",c=>d+=c);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(d)))' 2>/dev/null || printf '""')"
    exit 1
  fi

  # Find the JSON line with type=server-started in the log
  if [[ -f "$LOG_FILE" ]]; then
    SERVER_STARTED_LINE="$(grep -m1 '"server-started"' "$LOG_FILE" 2>/dev/null || true)"
    if [[ -n "$SERVER_STARTED_LINE" ]]; then
      break
    fi
  fi
done

# Check that the confirmation arrived
if [[ -z "$SERVER_STARTED_LINE" ]]; then
  # Kill the orphan process if it is still alive
  kill "$SERVER_PID" 2>/dev/null || true
  cleanup_failed_start
  printf '{"type":"error","message":"Сервер не запустился за 5 секунд","session_dir":"%s"}\n' "$SESSION_DIR"
  exit 1
fi

# Add session_dir and pid_file to the output so that the caller
# can run stop-server.sh correctly.
# Pass data as environment variables instead of interpolating it into code
# to prevent code injection through the log content.
ALFRED_RAW_LINE="$SERVER_STARTED_LINE" \
ALFRED_SESSION_DIR="$SESSION_DIR" \
ALFRED_PID_FILE="$PID_FILE" \
ALFRED_SERVER_PID="$SERVER_PID" \
node -e '
  const line = JSON.parse(process.env.ALFRED_RAW_LINE);
  const out = Object.assign({}, line, {
    session_dir: process.env.ALFRED_SESSION_DIR,
    pid_file: process.env.ALFRED_PID_FILE,
    server_pid: Number(process.env.ALFRED_SERVER_PID)
  });
  process.stdout.write(JSON.stringify(out) + "\n");
'

#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/runtime/logs"
PID_FILE="$ROOT_DIR/runtime/uvicorn_8765.pid"
LOG_FILE="$LOG_DIR/uvicorn_8765.log"

mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Uvicorn already running (pid=$old_pid)"
    exit 0
  fi
fi

nohup "$ROOT_DIR/deploy/local_run.sh" >"$LOG_FILE" 2>&1 < /dev/null &
new_pid="$!"
echo "$new_pid" > "$PID_FILE"

sleep 1
if kill -0 "$new_pid" 2>/dev/null; then
  echo "Started: pid=$new_pid"
  echo "Log: $LOG_FILE"
else
  echo "Failed to start. Check log: $LOG_FILE"
  exit 1
fi


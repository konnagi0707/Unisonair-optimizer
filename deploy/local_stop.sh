#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PID_FILE="$ROOT_DIR/runtime/uvicorn_8765.pid"
PORT="${UOA_PORT:-8765}"

stopped=0
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" || true)"
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" || true
    fi
    stopped=1
  fi
  rm -f "$PID_FILE"
fi

for pid in $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
  kill "$pid" || true
  stopped=1
done

if [ "$stopped" -eq 1 ]; then
  echo "Stopped uvicorn on port $PORT"
else
  echo "No uvicorn process found on port $PORT"
fi


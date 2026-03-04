#!/usr/bin/env sh
set -eu

PORT="${UOA_PORT:-8765}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Uvicorn is listening on port $PORT"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
else
  echo "No listener on port $PORT"
fi


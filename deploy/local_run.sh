#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

export UOA_DATA_ROOT="${UOA_DATA_ROOT:-$ROOT_DIR/data}"
export UOA_RUNTIME_DATA_DIR="${UOA_RUNTIME_DATA_DIR:-$ROOT_DIR/runtime}"
export UOA_HOST="${UOA_HOST:-127.0.0.1}"
export UOA_PORT="${UOA_PORT:-8765}"

mkdir -p "$UOA_RUNTIME_DATA_DIR"

cd "$ROOT_DIR"
exec python3 -m uvicorn app.main:app --host "$UOA_HOST" --port "$UOA_PORT"


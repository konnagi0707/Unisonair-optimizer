#!/usr/bin/env sh
set -eu

export UOA_RUNTIME_DATA_DIR="${UOA_RUNTIME_DATA_DIR:-/var/data/runtime}"
export UOA_DATA_ROOT="${UOA_DATA_ROOT:-/var/data/dataset}"
export PORT="${PORT:-10000}"

mkdir -p "$UOA_RUNTIME_DATA_DIR"
/app/deploy/ensure_dataset.sh

exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers

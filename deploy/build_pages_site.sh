#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/.pages_site}"
SRC_DIR="$ROOT_DIR/app/static"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/static"

cp "$SRC_DIR/index.html" "$OUT_DIR/index.html"
cp "$SRC_DIR/"*.css "$OUT_DIR/static/"
cp "$SRC_DIR/"*.js "$OUT_DIR/static/"
cp "$SRC_DIR/"*.svg "$OUT_DIR/static/"
touch "$OUT_DIR/.nojekyll"

echo "[pages] built site at: $OUT_DIR"

#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTRACT_ROOT_DEFAULT="$PROJECT_ROOT/../uoa-extract"
EXTRACT_ROOT="${1:-$EXTRACT_ROOT_DEFAULT}"

if [[ ! -d "$EXTRACT_ROOT/catalogs" || ! -d "$EXTRACT_ROOT/masters" ]]; then
  echo "Missing catalogs/masters under: $EXTRACT_ROOT"
  echo "Usage: ./deploy/make_dataset_bundle.sh /path/to/uoa-extract"
  exit 1
fi
if [[ ! -f "$PROJECT_ROOT/UOA大表 新人必看.xlsx" ]]; then
  echo "Missing workbook: $PROJECT_ROOT/UOA大表 新人必看.xlsx"
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$PROJECT_ROOT/deploy/dist"
OUT_FILE="$OUT_DIR/uoa_dataset_${STAMP}.tar.gz"
TMP_DIR="$(mktemp -d)"

mkdir -p "$OUT_DIR"
mkdir -p "$TMP_DIR/data"

cp -R "$EXTRACT_ROOT/catalogs" "$TMP_DIR/data/catalogs"
cp -R "$EXTRACT_ROOT/masters" "$TMP_DIR/data/masters"
cp "$PROJECT_ROOT/UOA大表 新人必看.xlsx" "$TMP_DIR/data/UOA大表 新人必看.xlsx"

tar -C "$TMP_DIR" -czf "$OUT_FILE" data
rm -rf "$TMP_DIR"

echo "Dataset bundle created:"
echo "$OUT_FILE"

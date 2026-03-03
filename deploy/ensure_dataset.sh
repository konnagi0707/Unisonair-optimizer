#!/usr/bin/env sh
set -eu

DATA_ROOT="${UOA_DATA_ROOT:-/var/data/dataset}"
DATASET_URL="${UOA_DATA_TARBALL_URL:-}"

required_ok() {
  [ -f "$DATA_ROOT/UOA大表 新人必看.xlsx" ] \
    && [ -d "$DATA_ROOT/catalogs" ] \
    && [ -d "$DATA_ROOT/masters" ]
}

if required_ok; then
  exit 0
fi

if [ -z "$DATASET_URL" ]; then
  echo "ERROR: dataset missing under $DATA_ROOT and UOA_DATA_TARBALL_URL is empty."
  echo "Please set UOA_DATA_TARBALL_URL to a public .tar.gz containing catalogs/, masters/, and UOA大表 新人必看.xlsx."
  exit 1
fi

mkdir -p "$DATA_ROOT"
TMP_FILE="$(mktemp /tmp/uoa_dataset.XXXXXX.tar.gz)"
TMP_DIR="$(mktemp -d /tmp/uoa_dataset_extract.XXXXXX)"

echo "Downloading dataset bundle..."
curl -fL "$DATASET_URL" -o "$TMP_FILE"

echo "Extracting dataset bundle..."
tar -xzf "$TMP_FILE" -C "$TMP_DIR"

if [ -d "$TMP_DIR/catalogs" ] && [ -d "$TMP_DIR/masters" ] && [ -f "$TMP_DIR/UOA大表 新人必看.xlsx" ]; then
  rm -rf "$DATA_ROOT/catalogs" "$DATA_ROOT/masters" "$DATA_ROOT/UOA大表 新人必看.xlsx"
  mv "$TMP_DIR/catalogs" "$DATA_ROOT/catalogs"
  mv "$TMP_DIR/masters" "$DATA_ROOT/masters"
  mv "$TMP_DIR/UOA大表 新人必看.xlsx" "$DATA_ROOT/UOA大表 新人必看.xlsx"
elif [ -d "$TMP_DIR/data" ] \
  && [ -d "$TMP_DIR/data/catalogs" ] \
  && [ -d "$TMP_DIR/data/masters" ] \
  && [ -f "$TMP_DIR/data/UOA大表 新人必看.xlsx" ]; then
  rm -rf "$DATA_ROOT/catalogs" "$DATA_ROOT/masters" "$DATA_ROOT/UOA大表 新人必看.xlsx"
  mv "$TMP_DIR/data/catalogs" "$DATA_ROOT/catalogs"
  mv "$TMP_DIR/data/masters" "$DATA_ROOT/masters"
  mv "$TMP_DIR/data/UOA大表 新人必看.xlsx" "$DATA_ROOT/UOA大表 新人必看.xlsx"
else
  echo "ERROR: dataset archive structure invalid."
  echo "Expected either:"
  echo "  /catalogs, /masters, /UOA大表 新人必看.xlsx"
  echo "or:"
  echo "  /data/catalogs, /data/masters, /data/UOA大表 新人必看.xlsx"
  exit 1
fi

rm -rf "$TMP_DIR"
rm -f "$TMP_FILE"

if ! required_ok; then
  echo "ERROR: dataset install verification failed."
  exit 1
fi

echo "Dataset ready at $DATA_ROOT"

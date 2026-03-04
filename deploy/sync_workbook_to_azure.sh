#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing command: $1" >&2
    exit 1
  fi
}

sha256_file() {
  local target="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target" | awk '{print $1}'
    return
  fi
  echo "ERROR: missing hash command (sha256sum or shasum)" >&2
  exit 1
}

require_cmd curl
require_cmd unzip
require_cmd file

WORKBOOK_SOURCE_URL="${WORKBOOK_SOURCE_URL:-}"
WORKBOOK_AUTH_HEADER="${WORKBOOK_AUTH_HEADER:-}"
WORKBOOK_COOKIE="${WORKBOOK_COOKIE:-}"
WORKBOOK_PATH="${WORKBOOK_PATH:-$ROOT_DIR/UOA大表 新人必看.xlsx}"
EXTRACT_ROOT="${EXTRACT_ROOT:-$ROOT_DIR/../uoa-extract}"
DOWNLOAD_MAX_TIME="${DOWNLOAD_MAX_TIME:-180}"
DOWNLOAD_CONNECT_TIMEOUT="${DOWNLOAD_CONNECT_TIMEOUT:-15}"
FORCE_SYNC="${FORCE_SYNC:-0}"
SKIP_AZURE_REFRESH="${SKIP_AZURE_REFRESH:-0}"

if [ -z "$WORKBOOK_SOURCE_URL" ]; then
  echo "ERROR: WORKBOOK_SOURCE_URL is required."
  echo "Example: export WORKBOOK_SOURCE_URL='https://example.com/UOA.xlsx'"
  exit 1
fi

tmp_file="$(mktemp /tmp/uoa_workbook.XXXXXX.xlsx)"
trap 'rm -f "$tmp_file"' EXIT

curl_args=(
  -fL
  --retry 3
  --retry-delay 2
  --connect-timeout "$DOWNLOAD_CONNECT_TIMEOUT"
  --max-time "$DOWNLOAD_MAX_TIME"
  "$WORKBOOK_SOURCE_URL"
  -o "$tmp_file"
)

if [ -n "$WORKBOOK_AUTH_HEADER" ]; then
  curl_args=(-H "$WORKBOOK_AUTH_HEADER" "${curl_args[@]}")
fi
if [ -n "$WORKBOOK_COOKIE" ]; then
  curl_args=(--cookie "$WORKBOOK_COOKIE" "${curl_args[@]}")
fi

echo "[1/6] Download workbook..."
curl "${curl_args[@]}"

mime_type="$(file -b --mime-type "$tmp_file" || true)"
if [ "$mime_type" = "text/html" ]; then
  echo "ERROR: downloaded content is HTML, not xlsx."
  echo "The source URL is likely a web/share page, not a direct file stream."
  exit 1
fi
if ! unzip -t "$tmp_file" >/dev/null 2>&1; then
  echo "ERROR: downloaded file is not a valid xlsx zip package."
  exit 1
fi

new_hash="$(sha256_file "$tmp_file")"
old_hash=""
if [ -f "$WORKBOOK_PATH" ]; then
  old_hash="$(sha256_file "$WORKBOOK_PATH")"
fi

if [ "$FORCE_SYNC" != "1" ] && [ -n "$old_hash" ] && [ "$old_hash" = "$new_hash" ]; then
  echo "[2/6] Workbook unchanged (sha256 matched), skip."
  exit 0
fi

echo "[2/6] Apply workbook update..."
cp "$tmp_file" "$WORKBOOK_PATH"

echo "[3/6] Build dataset tarball..."
"$ROOT_DIR/deploy/make_dataset_bundle.sh" "$EXTRACT_ROOT"

echo "[4/6] Upload dataset bundle to Azure Blob..."
"$ROOT_DIR/deploy/azure_upload_dataset_blob.sh"

if [ "$SKIP_AZURE_REFRESH" = "1" ]; then
  echo "[5/6] SKIP_AZURE_REFRESH=1, skip webapp update."
  exit 0
fi

dataset_url_file="$ROOT_DIR/deploy/dist/azure_dataset_url.txt"
if [ ! -f "$dataset_url_file" ]; then
  echo "ERROR: missing $dataset_url_file"
  exit 1
fi
export UOA_DATA_TARBALL_URL="$(cat "$dataset_url_file")"

echo "[5/6] Update Azure webapp dataset URL and restart..."
"$ROOT_DIR/deploy/azure_refresh_dataset.sh"

echo "[6/6] Done."
echo "Workbook updated and Azure backend refreshed."

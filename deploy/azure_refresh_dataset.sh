#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing command: $1" >&2
    exit 1
  fi
}

require_cmd az
require_cmd curl

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-uoa-rg}"
AZ_WEBAPP_NAME="${AZ_WEBAPP_NAME:-}"
UOA_DATA_TARBALL_URL="${UOA_DATA_TARBALL_URL:-}"
HEALTH_PATH="${HEALTH_PATH:-/api/healthz}"
HEALTH_WAIT_SEC="${HEALTH_WAIT_SEC:-240}"
HEALTH_INTERVAL_SEC="${HEALTH_INTERVAL_SEC:-5}"
FORCE_RESTART="${FORCE_RESTART:-0}"

if [ -z "$AZ_WEBAPP_NAME" ]; then
  echo "ERROR: AZ_WEBAPP_NAME is required."
  echo "Example: export AZ_WEBAPP_NAME=uoa-py-662909"
  exit 1
fi

if [ -z "$UOA_DATA_TARBALL_URL" ] && [ -f "$ROOT_DIR/deploy/dist/azure_dataset_url.txt" ]; then
  UOA_DATA_TARBALL_URL="$(cat "$ROOT_DIR/deploy/dist/azure_dataset_url.txt")"
fi

if [ -z "$UOA_DATA_TARBALL_URL" ]; then
  echo "ERROR: UOA_DATA_TARBALL_URL is empty."
  echo "Set env UOA_DATA_TARBALL_URL or run ./deploy/azure_upload_dataset_blob.sh first."
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "ERROR: Azure CLI not logged in. Run: az login"
  exit 1
fi

current_url="$(az webapp config appsettings list \
  --resource-group "$AZ_RESOURCE_GROUP" \
  --name "$AZ_WEBAPP_NAME" \
  --query "[?name=='UOA_DATA_TARBALL_URL'].value | [0]" \
  -o tsv 2>/dev/null || true)"

if [ "$FORCE_RESTART" != "1" ] && [ "$current_url" = "$UOA_DATA_TARBALL_URL" ]; then
  echo "UOA_DATA_TARBALL_URL unchanged; skip app restart."
  exit 0
fi

echo "[1/3] Update app setting UOA_DATA_TARBALL_URL..."
az webapp config appsettings set \
  --resource-group "$AZ_RESOURCE_GROUP" \
  --name "$AZ_WEBAPP_NAME" \
  --settings UOA_DATA_TARBALL_URL="$UOA_DATA_TARBALL_URL" \
  1>/dev/null

echo "[2/3] Restart web app..."
az webapp restart \
  --resource-group "$AZ_RESOURCE_GROUP" \
  --name "$AZ_WEBAPP_NAME" \
  1>/dev/null

default_host="$(az webapp show \
  --resource-group "$AZ_RESOURCE_GROUP" \
  --name "$AZ_WEBAPP_NAME" \
  --query defaultHostName \
  -o tsv)"
health_url="https://${default_host}${HEALTH_PATH}"

echo "[3/3] Wait for health check: $health_url"
start_ts="$(date +%s)"
while true; do
  if curl -fsS --max-time 10 "$health_url" >/dev/null 2>&1; then
    echo "Healthy: $health_url"
    break
  fi
  now_ts="$(date +%s)"
  elapsed="$((now_ts - start_ts))"
  if [ "$elapsed" -ge "$HEALTH_WAIT_SEC" ]; then
    echo "ERROR: health check timeout after ${elapsed}s"
    echo "Please inspect Azure Log stream."
    exit 1
  fi
  sleep "$HEALTH_INTERVAL_SEC"
done

echo
echo "Dataset URL refresh done."
echo "API base: https://${default_host}"

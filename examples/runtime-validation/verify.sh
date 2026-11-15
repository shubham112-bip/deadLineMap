#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${DEADLINEMAP_PORT:-18080}"
BASE_URL="http://127.0.0.1:${PORT}"

compose() {
  docker compose --project-name deadlinemap-runtime --file "$SCRIPT_DIR/compose.yaml" "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker was not found. Install/start Docker Desktop or Docker Engine first." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required (the 'docker compose' command)." >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required." >&2
  exit 1
fi

echo "Starting the isolated NGINX + Gunicorn stack..."
compose up --build --detach

ready=0
for attempt in {1..30}; do
  if curl --silent --fail --max-time 2 "$BASE_URL/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" != "1" ]]; then
  echo "The local stack did not become ready. Container logs:" >&2
  compose logs --no-color >&2 || true
  exit 1
fi

echo "Sending one request to the 6-second endpoint..."
result="$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code} %{time_total}' --max-time 15 "$BASE_URL/slow")"
status="${result%% *}"
elapsed="${result#* }"

if [[ "$status" != "502" ]]; then
  echo "Expected NGINX HTTP 502 after Gunicorn's worker timeout; got: $result" >&2
  compose logs --no-color >&2 || true
  exit 1
fi

app_logs="$(compose logs --no-color app)"
if ! printf '%s\n' "$app_logs" | grep -q "WORKER TIMEOUT"; then
  echo "NGINX returned 502, but Gunicorn's WORKER TIMEOUT log was not found." >&2
  printf '%s\n' "$app_logs" >&2
  exit 1
fi

echo "PASS: NGINX returned HTTP $status after ${elapsed}s."
echo "PASS: Gunicorn logged WORKER TIMEOUT."
echo "The live result matches the DM002 ordering: Gunicorn timeout 2s < NGINX read interval 10s."

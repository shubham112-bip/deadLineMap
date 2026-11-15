#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${DEADLINEMAP_DM001_PORT:-18082}"
BASE_URL="http://127.0.0.1:${PORT}"

compose() {
  docker compose --project-name deadlinemap-runtime-dm001 --file "$SCRIPT_DIR/compose.yaml" "$@"
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

get_remote_port() {
  python -c 'import json, sys; print(json.load(sys.stdin)["remote_port"])'
}

echo "Starting the isolated DM001 NGINX + Gunicorn stack..."
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
  echo "The local DM001 stack did not become ready. Container logs:" >&2
  compose logs --no-color >&2 || true
  exit 1
fi

echo "Sending two immediate requests to check NGINX upstream connection reuse..."
first="$(curl --silent --show-error --fail --max-time 5 "$BASE_URL/connection-info")"
second="$(curl --silent --show-error --fail --max-time 5 "$BASE_URL/connection-info")"
first_port="$(printf '%s' "$first" | get_remote_port)"
second_port="$(printf '%s' "$second" | get_remote_port)"

if [[ "$first_port" != "$second_port" ]]; then
  echo "Expected NGINX to reuse the immediate upstream connection; remote ports differ: $first_port vs $second_port" >&2
  compose logs --no-color >&2 || true
  exit 1
fi
echo "PASS: immediate requests reused Gunicorn peer port $first_port."

echo "Waiting 4 seconds (Gunicorn keepalive=2s, NGINX upstream keepalive_timeout=10s)..."
sleep 4

body_file="$(mktemp)"
trap 'rm -f "$body_file"; cleanup' EXIT
status="$(curl --silent --show-error --output "$body_file" --write-out '%{http_code}' --max-time 10 "$BASE_URL/connection-info")"

if [[ "$status" == "200" ]]; then
  third_port="$(get_remote_port < "$body_file")"
  if [[ "$third_port" == "$second_port" ]]; then
    echo "Gunicorn peer port did not rotate after its 2s idle keepalive; observed port: $third_port" >&2
    compose logs --no-color >&2 || true
    exit 1
  fi
  echo "PASS: Gunicorn closed the idle connection and NGINX opened a fresh one (port $second_port -> $third_port)."
elif [[ "$status" == "502" ]]; then
  nginx_logs="$(compose logs --no-color nginx)"
  if ! printf '%s\n' "$nginx_logs" | grep -qi "upstream"; then
    echo "Observed HTTP 502 but could not confirm an upstream connection error in NGINX logs." >&2
    printf '%s\n' "$nginx_logs" >&2
    exit 1
  fi
  echo "OBSERVED: NGINX returned HTTP 502 while handling the stale upstream connection."
else
  echo "Unexpected response after the idle gap: HTTP $status" >&2
  cat "$body_file" >&2 || true
  compose logs --no-color >&2 || true
  exit 1
fi

echo "PASS: DM001 configuration was exercised with real NGINX and Gunicorn."
echo "A clean reconnect is valid; this mismatch is a needs-review race, not a guaranteed failure."

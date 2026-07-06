#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
EMAIL="${EMAIL:-smoke-$(date +%s)@example.com}"
PASSWORD="${PASSWORD:-correct-horse-battery-staple}"
TMP_FILE="$(mktemp)"

cleanup() {
  rm -f "$TMP_FILE"
}
trap cleanup EXIT

extract_json_value() {
  local key="$1"
  sed -E "s/.*\"${key}\":\"([^\"]+)\".*/\\1/"
}

expect_status() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL ${label}: expected HTTP ${expected}, got ${actual}" >&2
    exit 1
  fi

  echo "OK ${label}"
}

echo "Testing ${BASE_URL}"

health_status="$(curl -sS -o /tmp/offline-hub-health.json -w "%{http_code}" "${BASE_URL}/health")"
expect_status "200" "$health_status" "health"

db_status="$(curl -sS -o /tmp/offline-hub-db-health.json -w "%{http_code}" "${BASE_URL}/health/db")"
expect_status "200" "$db_status" "database health"

register_status="$(
  curl -sS -o /tmp/offline-hub-register.json -w "%{http_code}" \
    -X POST "${BASE_URL}/api/v1/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}"
)"
expect_status "201" "$register_status" "register"

login_body="$(
  curl -sS -X POST "${BASE_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}"
)"
ACCESS_TOKEN="$(printf "%s" "$login_body" | extract_json_value "access_token")"
REFRESH_TOKEN="$(printf "%s" "$login_body" | extract_json_value "refresh_token")"

if [[ -z "$ACCESS_TOKEN" || "$ACCESS_TOKEN" == "$login_body" ]]; then
  echo "FAIL login: missing access token" >&2
  exit 1
fi
if [[ -z "$REFRESH_TOKEN" || "$REFRESH_TOKEN" == "$login_body" ]]; then
  echo "FAIL login: missing refresh token" >&2
  exit 1
fi
echo "OK login"

refresh_status="$(
  curl -sS -o /tmp/offline-hub-refresh.json -w "%{http_code}" \
    -X POST "${BASE_URL}/api/v1/auth/refresh" \
    -H "Content-Type: application/json" \
    -d "{\"refresh_token\":\"${REFRESH_TOKEN}\"}"
)"
expect_status "200" "$refresh_status" "refresh"

me_status="$(
  curl -sS -o /tmp/offline-hub-me.json -w "%{http_code}" \
    "${BASE_URL}/api/v1/users/me" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}"
)"
expect_status "200" "$me_status" "users me"

printf "Backups run every night.\n" > "$TMP_FILE"
upload_body="$(
  curl -sS -X POST "${BASE_URL}/api/v1/documents" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -F "file=@${TMP_FILE};filename=policy.txt;type=text/plain"
)"
DOCUMENT_ID="$(printf "%s" "$upload_body" | sed -E 's/.*"id":([0-9]+).*/\1/')"
if [[ -z "$DOCUMENT_ID" || "$DOCUMENT_ID" == "$upload_body" ]]; then
  echo "FAIL upload: missing document id" >&2
  exit 1
fi
echo "OK upload"

list_status="$(
  curl -sS -o /tmp/offline-hub-documents.json -w "%{http_code}" \
    "${BASE_URL}/api/v1/documents" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}"
)"
expect_status "200" "$list_status" "list documents"

delete_status="$(
  curl -sS -o /tmp/offline-hub-delete.json -w "%{http_code}" \
    -X DELETE "${BASE_URL}/api/v1/documents/${DOCUMENT_ID}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}"
)"
expect_status "204" "$delete_status" "delete document"

echo "Smoke test completed for ${EMAIL}"

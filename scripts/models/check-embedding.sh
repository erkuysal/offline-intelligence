#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/embedding-env.sh"
configure_embedding_env

if [[ -f "$EMBEDDING_SERVER_PID_FILE" ]]; then
  pid="$(<"$EMBEDDING_SERVER_PID_FILE")"
  if llama_pid_running "$pid"; then
    echo "PID file: ${EMBEDDING_SERVER_PID_FILE} (${pid}, running)"
  else
    echo "PID file: ${EMBEDDING_SERVER_PID_FILE} (${pid}, stale)"
  fi
else
  echo "PID file: ${EMBEDDING_SERVER_PID_FILE} (missing)"
fi

echo "Checking embedding server models at ${EMBEDDING_BASE_URL}/models"
curl -fsS "${EMBEDDING_BASE_URL}/models" >/tmp/offline-hub-embedding-models.json
echo "OK models endpoint"

echo "Checking embedding generation"
curl -fsS \
  -X POST "${EMBEDDING_BASE_URL}/embeddings" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${EMBEDDING_MODEL}\",\"input\":[\"embedding health check\"]}" \
  >/tmp/offline-hub-embedding-check.json
echo "OK embeddings endpoint"

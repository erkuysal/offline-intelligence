#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/embedding-env.sh"
configure_embedding_env

if [[ ! -f "$EMBEDDING_SERVER_PID_FILE" ]]; then
  if embedding_api_available; then
    echo "Embedding server responds at ${EMBEDDING_BASE_URL}, but no PID file exists." >&2
    echo "Stop the external process manually or restart it with ./manage.py embedding-start." >&2
    exit 1
  fi
  echo "Embedding server is not running (${EMBEDDING_SERVER_PID_FILE} missing)"
  exit 0
fi

pid="$(<"$EMBEDDING_SERVER_PID_FILE")"
if ! llama_pid_running "$pid"; then
  echo "Removing stale embedding server PID file: ${EMBEDDING_SERVER_PID_FILE}"
  rm -f "$EMBEDDING_SERVER_PID_FILE"
  exit 0
fi

echo "Stopping embedding server PID ${pid}"
kill -TERM "$pid"
for ((elapsed = 0; elapsed < EMBEDDING_SERVER_SHUTDOWN_TIMEOUT_SECONDS; elapsed++)); do
  if ! llama_pid_running "$pid"; then
    rm -f "$EMBEDDING_SERVER_PID_FILE"
    echo "Embedding server stopped"
    exit 0
  fi
  sleep 1
done

echo "Embedding server did not stop after ${EMBEDDING_SERVER_SHUTDOWN_TIMEOUT_SECONDS}s; sending SIGKILL" >&2
kill -KILL "$pid" 2>/dev/null || true
rm -f "$EMBEDDING_SERVER_PID_FILE"

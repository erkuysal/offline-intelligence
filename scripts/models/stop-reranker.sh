#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reranker-env.sh"
configure_reranker_env

if [[ ! -f "$RERANKER_SERVER_PID_FILE" ]]; then
  echo "Reranker server is not running (${RERANKER_SERVER_PID_FILE} missing)"
  exit 0
fi
pid="$(<"$RERANKER_SERVER_PID_FILE")"
if ! llama_pid_running "$pid"; then
  rm -f "$RERANKER_SERVER_PID_FILE"
  exit 0
fi
echo "Stopping reranker server PID ${pid}"
kill -TERM "$pid"
for ((elapsed = 0; elapsed < RERANKER_SERVER_SHUTDOWN_TIMEOUT_SECONDS; elapsed++)); do
  if ! llama_pid_running "$pid"; then
    rm -f "$RERANKER_SERVER_PID_FILE"
    echo "Reranker server stopped"
    exit 0
  fi
  sleep 1
done
kill -KILL "$pid" 2>/dev/null || true
rm -f "$RERANKER_SERVER_PID_FILE"

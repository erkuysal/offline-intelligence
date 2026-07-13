#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/llm-env.sh"
configure_llama_env

if [[ ! -f "$LLAMA_PID_FILE" ]]; then
  if llama_api_available; then
    echo "llama-server responds at ${LLM_BASE_URL}, but no PID file exists."
    echo "Stop the external process manually or restart it with ./manage.py llm-start."
    exit 1
  fi

  echo "llama-server is not running (${LLAMA_PID_FILE} missing)"
  exit 0
fi

pid="$(<"$LLAMA_PID_FILE")"
if ! llama_pid_running "$pid"; then
  echo "Removing stale llama-server PID file: ${LLAMA_PID_FILE}"
  rm -f "$LLAMA_PID_FILE"
  exit 0
fi

echo "Stopping llama-server PID ${pid}"
kill -TERM "$pid"

for ((elapsed = 0; elapsed < LLAMA_SHUTDOWN_TIMEOUT_SECONDS; elapsed++)); do
  if ! llama_pid_running "$pid"; then
    rm -f "$LLAMA_PID_FILE"
    echo "llama-server stopped"
    exit 0
  fi
  sleep 1
done

echo "llama-server did not stop after ${LLAMA_SHUTDOWN_TIMEOUT_SECONDS}s; sending SIGKILL" >&2
kill -KILL "$pid" 2>/dev/null || true
rm -f "$LLAMA_PID_FILE"

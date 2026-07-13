#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/llm-env.sh"
configure_llama_env

if [[ -f "$LLAMA_PID_FILE" ]]; then
  existing_pid="$(<"$LLAMA_PID_FILE")"
  if llama_pid_running "$existing_pid"; then
    echo "PID file: ${LLAMA_PID_FILE} (${existing_pid}, running)"
  else
    echo "PID file: ${LLAMA_PID_FILE} (${existing_pid}, stale)"
  fi
else
  echo "PID file: ${LLAMA_PID_FILE} (missing)"
fi

echo "Checking llama-server models at ${LLM_BASE_URL}/models"
curl -fsS "${LLM_BASE_URL}/models" >/tmp/offline-hub-llama-models.json
echo "OK models endpoint"

echo "Checking llama-server chat completion"
curl -fsS \
  -X POST "${LLM_BASE_URL}/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${LLM_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Ready?\"}],\"temperature\":0,\"max_tokens\":1,\"stream\":false}" \
  >/tmp/offline-hub-llama-chat.json
echo "OK chat completion"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"

load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *=* ]] || continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

    if [[ "$value" =~ ^\".*\"$ || "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:${#value}-2}"
    fi

    export "$key=$value"
  done < "$file"
}

load_env_file "$ENV_FILE"

LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLM_BASE_URL="${LLM_BASE_URL:-http://${LLAMA_HOST}:${LLAMA_PORT}/v1}"
LLM_MODEL="${LLM_MODEL:-${LLAMA_MODEL_REPO:-ggml-org/gemma-3-1b-it-GGUF:Q4_K_M}}"

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

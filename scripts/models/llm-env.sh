#!/usr/bin/env bash

llama_root_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

load_llama_env_file() {
  local file="$1"
  local override="${2:-false}"
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
    if [[ "$override" != "true" && -v "$key" ]]; then
      continue
    fi

    if [[ "$value" =~ ^\".*\"$ || "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:${#value}-2}"
    fi

    export "$key=$value"
  done < "$file"
}

expand_llama_path() {
  local path="$1"
  if [[ "$path" == "~" ]]; then
    printf "%s\n" "$HOME"
  elif [[ "$path" == "~/"* ]]; then
    printf "%s/%s\n" "$HOME" "${path#"~/"}"
  else
    printf "%s\n" "$path"
  fi
}

configure_llama_env() {
  ROOT_DIR="$(llama_root_dir)"
  if [[ -n "${APP_ENV_FILE:-}" ]]; then
    ENV_FILE="$APP_ENV_FILE"
    load_llama_env_file "$ENV_FILE"
  elif [[ -n "${ENV_FILE:-}" ]]; then
    load_llama_env_file "$ENV_FILE"
  else
    ENV_FILE="${ROOT_DIR}/config/env/dev.env"
    load_llama_env_file "${ROOT_DIR}/config/env/local.env"
    load_llama_env_file "$ENV_FILE"
  fi

  LLAMA_PROFILE="${LLAMA_PROFILE:-}"
  LLAMA_PROFILE_DIR="${LLAMA_PROFILE_DIR:-${ROOT_DIR}/config/models}"
  if [[ -n "$LLAMA_PROFILE" ]]; then
    if [[ "$LLAMA_PROFILE" == */* ]]; then
      LLAMA_PROFILE_FILE="$(expand_llama_path "$LLAMA_PROFILE")"
    else
      LLAMA_PROFILE_FILE="${LLAMA_PROFILE_DIR}/${LLAMA_PROFILE}.env"
    fi

    if [[ ! -f "$LLAMA_PROFILE_FILE" ]]; then
      echo "llama profile not found: ${LLAMA_PROFILE_FILE}" >&2
      exit 1
    fi

    load_llama_env_file "$LLAMA_PROFILE_FILE" true
  fi

  LLAMA_CPP_BIN="$(expand_llama_path "${LLAMA_CPP_BIN:-~/tools/llama.cpp/build/bin/llama-server}")"
  LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
  LLAMA_PORT="${LLAMA_PORT:-8080}"
  LLAMA_MODEL_REPO="${LLAMA_MODEL_REPO:-${LLM_MODEL:-ggml-org/gemma-3-1b-it-GGUF:Q4_K_M}}"
  LLAMA_MODEL_PATH="${LLAMA_MODEL_PATH:-}"
  LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-4096}"
  LLAMA_THREADS="${LLAMA_THREADS:-}"
  LLAMA_PARALLEL="${LLAMA_PARALLEL:-1}"
  LLAMA_BATCH_SIZE="${LLAMA_BATCH_SIZE:-}"
  LLAMA_UBATCH_SIZE="${LLAMA_UBATCH_SIZE:-}"
  LLAMA_GPU_LAYERS="${LLAMA_GPU_LAYERS:-}"
  LLAMA_FLASH_ATTN="${LLAMA_FLASH_ATTN:-}"
  LLM_ADAPTER_PATH="${LLM_ADAPTER_PATH:-}"
  LLM_ADAPTER_MANIFEST="${LLM_ADAPTER_MANIFEST:-}"
  LLM_ADAPTER_SCALE="${LLM_ADAPTER_SCALE:-1.0}"
  LLM_ADAPTER_ID="${LLM_ADAPTER_ID:-}"
  LLM_ADAPTER_SHA256="${LLM_ADAPTER_SHA256:-}"
  LLAMA_EXTRA_ARGS="${LLAMA_EXTRA_ARGS:-}"
  LLAMA_PID_FILE="$(expand_llama_path "${LLAMA_PID_FILE:-${ROOT_DIR}/var/run/llm.pid}")"
  LLAMA_SHUTDOWN_TIMEOUT_SECONDS="${LLAMA_SHUTDOWN_TIMEOUT_SECONDS:-15}"
  LLM_BASE_URL="${LLM_BASE_URL:-http://${LLAMA_HOST}:${LLAMA_PORT}/v1}"
  LLM_MODEL="${LLM_MODEL:-${LLAMA_MODEL_REPO}}"
}

llama_api_available() {
  curl -fsS --max-time 2 "${LLM_BASE_URL}/models" >/dev/null 2>&1
}

llama_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

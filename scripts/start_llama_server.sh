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

expand_path() {
  local path="$1"
  if [[ "$path" == "~" ]]; then
    printf "%s\n" "$HOME"
  elif [[ "$path" == "~/"* ]]; then
    printf "%s/%s\n" "$HOME" "${path#"~/"}"
  else
    printf "%s\n" "$path"
  fi
}

load_env_file "$ENV_FILE"

LLAMA_CPP_BIN="$(expand_path "${LLAMA_CPP_BIN:-~/tools/llama.cpp/build/bin/llama-server}")"
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

if [[ ! -x "$LLAMA_CPP_BIN" ]]; then
  echo "llama-server binary not found or not executable: ${LLAMA_CPP_BIN}" >&2
  echo "Set LLAMA_CPP_BIN in .env or rebuild llama.cpp." >&2
  exit 1
fi

args=(
  "$LLAMA_CPP_BIN"
  --host "$LLAMA_HOST"
  --port "$LLAMA_PORT"
  -c "$LLAMA_CTX_SIZE"
)

if [[ -n "$LLAMA_MODEL_PATH" ]]; then
  args+=(-m "$(expand_path "$LLAMA_MODEL_PATH")")
elif [[ -n "$LLAMA_MODEL_REPO" ]]; then
  args+=(-hf "$LLAMA_MODEL_REPO")
else
  echo "Set LLAMA_MODEL_PATH or LLAMA_MODEL_REPO before starting llama-server." >&2
  exit 1
fi

[[ -n "$LLAMA_THREADS" ]] && args+=(-t "$LLAMA_THREADS")
[[ -n "$LLAMA_PARALLEL" ]] && args+=(-np "$LLAMA_PARALLEL")
[[ -n "$LLAMA_BATCH_SIZE" ]] && args+=(-b "$LLAMA_BATCH_SIZE")
[[ -n "$LLAMA_UBATCH_SIZE" ]] && args+=(-ub "$LLAMA_UBATCH_SIZE")
[[ -n "$LLAMA_GPU_LAYERS" ]] && args+=(-ngl "$LLAMA_GPU_LAYERS")

echo "Starting llama-server on http://${LLAMA_HOST}:${LLAMA_PORT}"
echo "Model: ${LLAMA_MODEL_PATH:-${LLAMA_MODEL_REPO}}"
if [[ -n "$LLAMA_GPU_LAYERS" ]]; then
  echo "GPU layer offload: ${LLAMA_GPU_LAYERS}"
else
  echo "GPU layer offload: llama.cpp default"
fi

exec "${args[@]}"

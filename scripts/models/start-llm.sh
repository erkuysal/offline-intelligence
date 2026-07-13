#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/llm-env.sh"
configure_llama_env

if [[ -f "$LLAMA_PID_FILE" ]]; then
  existing_pid="$(<"$LLAMA_PID_FILE")"
  if llama_pid_running "$existing_pid"; then
    echo "llama-server already running with PID ${existing_pid} (${LLAMA_PID_FILE})"
    exit 0
  fi

  echo "Removing stale llama-server PID file: ${LLAMA_PID_FILE}"
  rm -f "$LLAMA_PID_FILE"
fi

if llama_api_available; then
  echo "llama-server already responds at ${LLM_BASE_URL}"
  echo "No new process started."
  exit 0
fi

if [[ ! -x "$LLAMA_CPP_BIN" ]]; then
  echo "llama-server binary not found or not executable: ${LLAMA_CPP_BIN}" >&2
  echo "Set LLAMA_CPP_BIN in ${ENV_FILE} or rebuild llama.cpp." >&2
  exit 1
fi

args=(
  "$LLAMA_CPP_BIN"
  --host "$LLAMA_HOST"
  --port "$LLAMA_PORT"
  -c "$LLAMA_CTX_SIZE"
)

if [[ -n "$LLAMA_MODEL_PATH" ]]; then
  resolved_model_path="$(expand_llama_path "$LLAMA_MODEL_PATH")"
  if [[ ! -r "$resolved_model_path" ]]; then
    echo "LLM model file is missing or unreadable: ${resolved_model_path}" >&2
    echo "Set LLAMA_MODEL_PATH to a readable GGUF file or clear it to use LLAMA_MODEL_REPO." >&2
    exit 2
  fi
  args+=(-m "$resolved_model_path")
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
case "${LLAMA_FLASH_ATTN,,}" in
  1|true|yes|on) args+=(--flash-attn on) ;;
esac
if [[ -n "$LLAMA_EXTRA_ARGS" ]]; then
  read -r -a extra_args <<< "$LLAMA_EXTRA_ARGS"
  args+=("${extra_args[@]}")
fi

mkdir -p "$(dirname "$LLAMA_PID_FILE")"

child_pid=""
cleanup() {
  rm -f "$LLAMA_PID_FILE"
}

shutdown_child() {
  local signal="$1"
  if [[ -n "$child_pid" ]] && llama_pid_running "$child_pid"; then
    echo "Forwarding ${signal} to llama-server PID ${child_pid}"
    kill "-${signal}" "$child_pid" 2>/dev/null || true
    wait "$child_pid" || true
  fi
  cleanup
}

trap 'shutdown_child TERM; exit 143' TERM
trap 'shutdown_child INT; exit 130' INT
trap cleanup EXIT

echo "Starting llama-server on http://${LLAMA_HOST}:${LLAMA_PORT}"
echo "Model: ${LLAMA_MODEL_PATH:-${LLAMA_MODEL_REPO}}"
echo "PID file: ${LLAMA_PID_FILE}"
[[ -n "${LLAMA_PROFILE:-}" ]] && echo "Profile: ${LLAMA_PROFILE}"
[[ -n "$LLAMA_THREADS" ]] && echo "Threads: ${LLAMA_THREADS}"
[[ -n "$LLAMA_BATCH_SIZE" ]] && echo "Batch size: ${LLAMA_BATCH_SIZE}"
if [[ -n "$LLAMA_GPU_LAYERS" ]]; then
  echo "GPU layer offload: ${LLAMA_GPU_LAYERS}"
else
  echo "GPU layer offload: llama.cpp default"
fi
case "${LLAMA_FLASH_ATTN,,}" in
  1|true|yes|on) echo "Flash Attention: enabled" ;;
esac

"${args[@]}" &
child_pid="$!"
printf "%s\n" "$child_pid" > "$LLAMA_PID_FILE"
wait "$child_pid"

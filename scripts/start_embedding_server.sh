#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/embedding_env.sh"
configure_embedding_env

if [[ -f "$EMBEDDING_SERVER_PID_FILE" ]]; then
  existing_pid="$(<"$EMBEDDING_SERVER_PID_FILE")"
  if llama_pid_running "$existing_pid"; then
    echo "Embedding server already running with PID ${existing_pid} (${EMBEDDING_SERVER_PID_FILE})"
    exit 0
  fi
  echo "Removing stale embedding server PID file: ${EMBEDDING_SERVER_PID_FILE}"
  rm -f "$EMBEDDING_SERVER_PID_FILE"
fi

if embedding_api_available; then
  echo "Embedding server already responds at ${EMBEDDING_BASE_URL}"
  echo "No new process started."
  exit 0
fi

if [[ ! -x "$EMBEDDING_LLAMA_CPP_BIN" ]]; then
  echo "llama-server binary not found or not executable: ${EMBEDDING_LLAMA_CPP_BIN}" >&2
  exit 1
fi

args=(
  "$EMBEDDING_LLAMA_CPP_BIN"
  --host "$EMBEDDING_SERVER_HOST"
  --port "$EMBEDDING_SERVER_PORT"
  --embedding
  --alias "$EMBEDDING_SERVER_ALIAS"
  -c "$EMBEDDING_SERVER_CTX_SIZE"
)

if [[ -n "$EMBEDDING_SERVER_MODEL_PATH" ]]; then
  args+=(-m "$(expand_llama_path "$EMBEDDING_SERVER_MODEL_PATH")")
else
  args+=(-hf "$EMBEDDING_SERVER_MODEL_REPO")
fi

[[ -n "$EMBEDDING_SERVER_THREADS" ]] && args+=(-t "$EMBEDDING_SERVER_THREADS")
[[ -n "$EMBEDDING_SERVER_BATCH_SIZE" ]] && args+=(-b "$EMBEDDING_SERVER_BATCH_SIZE")
[[ -n "$EMBEDDING_SERVER_UBATCH_SIZE" ]] && args+=(-ub "$EMBEDDING_SERVER_UBATCH_SIZE")
[[ -n "$EMBEDDING_SERVER_GPU_LAYERS" ]] && args+=(-ngl "$EMBEDDING_SERVER_GPU_LAYERS")
case "${EMBEDDING_SERVER_FLASH_ATTN,,}" in
  1|true|yes|on) args+=(--flash-attn on) ;;
esac
if [[ -n "$EMBEDDING_SERVER_EXTRA_ARGS" ]]; then
  read -r -a extra_args <<< "$EMBEDDING_SERVER_EXTRA_ARGS"
  args+=("${extra_args[@]}")
fi

mkdir -p "$(dirname "$EMBEDDING_SERVER_PID_FILE")"
child_pid=""
cleanup() {
  rm -f "$EMBEDDING_SERVER_PID_FILE"
}
shutdown_child() {
  local signal="$1"
  if [[ -n "$child_pid" ]] && llama_pid_running "$child_pid"; then
    echo "Forwarding ${signal} to embedding server PID ${child_pid}"
    kill "-${signal}" "$child_pid" 2>/dev/null || true
    wait "$child_pid" || true
  fi
  cleanup
}
trap 'shutdown_child TERM; exit 143' TERM
trap 'shutdown_child INT; exit 130' INT
trap cleanup EXIT

echo "Starting embedding server on http://${EMBEDDING_SERVER_HOST}:${EMBEDDING_SERVER_PORT}"
echo "Model: ${EMBEDDING_SERVER_MODEL_PATH:-${EMBEDDING_SERVER_MODEL_REPO}}"
echo "Alias: ${EMBEDDING_SERVER_ALIAS}"
echo "PID file: ${EMBEDDING_SERVER_PID_FILE}"

"${args[@]}" &
child_pid="$!"
printf "%s\n" "$child_pid" > "$EMBEDDING_SERVER_PID_FILE"
wait "$child_pid"

#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reranker-env.sh"
configure_reranker_env

if [[ -f "$RERANKER_SERVER_PID_FILE" ]]; then
  existing_pid="$(<"$RERANKER_SERVER_PID_FILE")"
  if llama_pid_running "$existing_pid"; then
    echo "Reranker server already running with PID ${existing_pid}"
    exit 0
  fi
  rm -f "$RERANKER_SERVER_PID_FILE"
fi
if reranker_api_available; then
  echo "Reranker server already responds at ${RERANKER_BASE_URL}"
  exit 0
fi
if [[ ! -x "$RERANKER_LLAMA_CPP_BIN" ]]; then
  echo "llama-server binary not found or not executable: ${RERANKER_LLAMA_CPP_BIN}" >&2
  exit 1
fi

args=("$RERANKER_LLAMA_CPP_BIN" --host "$RERANKER_SERVER_HOST" --port "$RERANKER_SERVER_PORT" --reranking --alias "$RERANKER_SERVER_ALIAS" -c "$RERANKER_SERVER_CTX_SIZE")
if [[ -n "$RERANKER_SERVER_MODEL_PATH" ]]; then
  model_path="$(expand_llama_path "$RERANKER_SERVER_MODEL_PATH")"
  [[ -r "$model_path" ]] || { echo "Reranker model is unreadable: ${model_path}" >&2; exit 2; }
  args+=(-m "$model_path")
else
  args+=(-hf "$RERANKER_SERVER_MODEL_REPO")
fi
[[ -n "$RERANKER_SERVER_THREADS" ]] && args+=(-t "$RERANKER_SERVER_THREADS")
[[ -n "$RERANKER_SERVER_PARALLEL" ]] && args+=(-np "$RERANKER_SERVER_PARALLEL")
[[ -n "$RERANKER_SERVER_GPU_LAYERS" ]] && args+=(-ngl "$RERANKER_SERVER_GPU_LAYERS")
if [[ -n "$RERANKER_SERVER_EXTRA_ARGS" ]]; then
  read -r -a extra_args <<< "$RERANKER_SERVER_EXTRA_ARGS"
  args+=("${extra_args[@]}")
fi

mkdir -p "$(dirname "$RERANKER_SERVER_PID_FILE")"
child_pid=""
cleanup() { rm -f "$RERANKER_SERVER_PID_FILE"; }
shutdown_child() {
  if [[ -n "$child_pid" ]] && llama_pid_running "$child_pid"; then
    kill -"$1" "$child_pid" 2>/dev/null || true
    wait "$child_pid" || true
  fi
  cleanup
}
trap 'shutdown_child TERM; exit 143' TERM
trap 'shutdown_child INT; exit 130' INT
trap cleanup EXIT

echo "Starting reranker server on http://${RERANKER_SERVER_HOST}:${RERANKER_SERVER_PORT}"
echo "Model: ${RERANKER_SERVER_MODEL_PATH:-${RERANKER_SERVER_MODEL_REPO}}"
"${args[@]}" &
child_pid="$!"
printf "%s\n" "$child_pid" > "$RERANKER_SERVER_PID_FILE"
wait "$child_pid"

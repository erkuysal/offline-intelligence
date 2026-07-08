#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export LLAMA_CPP_BIN="${LLAMA_CPP_BIN:-~/tools/llama.cpp/build/bin/llama-server}"
export LLAMA_MODEL_REPO="${LLAMA_MODEL_REPO:-ggml-org/Meta-Llama-3.1-8B-Instruct-Q4_0-GGUF:Q4_0}"
export LLM_MODEL="${LLM_MODEL:-ggml-org/Meta-Llama-3.1-8B-Instruct-Q4_0-GGUF:Q4_0}"
export LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
export LLAMA_PORT="${LLAMA_PORT:-8080}"
export LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-8192}"
export LLAMA_GPU_LAYERS="${LLAMA_GPU_LAYERS:-99}"

exec "${SCRIPT_DIR}/start_llama_server.sh"

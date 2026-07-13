#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ACTION=${1:-start}

APP_ENV_FILE=${APP_ENV_FILE:-${ROOT}/.env.e2e}
if [[ ! -f "$APP_ENV_FILE" ]]; then
  echo "E2E environment file not found: ${APP_ENV_FILE}" >&2
  exit 2
fi
export APP_ENV_FILE
set -a
source "$APP_ENV_FILE"
set +a

case "${E2E_MODEL_MODE:-fake}" in
  fake)
    export LLM_BACKEND=fake
    export LLM_WARMUP_ENABLED=false
    export LLM_MAX_CONCURRENT_REQUESTS=${E2E_LLM_MAX_CONCURRENT_REQUESTS:-16}
    export EMBEDDING_BACKEND=fake
    export EMBEDDING_MODEL=fake-bow
    ;;
  real)
    export LLM_BACKEND=openai_compatible
    export LLM_BASE_URL=${LLM_BASE_URL:-http://127.0.0.1:8080/v1}
    export LLM_WARMUP_ENABLED=true
    export LLM_MAX_CONCURRENT_REQUESTS=${E2E_LLM_MAX_CONCURRENT_REQUESTS:-1}
    export EMBEDDING_BACKEND=openai_compatible
    export EMBEDDING_BASE_URL=${EMBEDDING_BASE_URL:-http://127.0.0.1:8081/v1}
    echo "Starting opt-in E2E API with real local model servers" >&2
    ;;
  *)
    echo "E2E_MODEL_MODE must be 'fake' or 'real'" >&2
    exit 2
    ;;
esac

run_python() {
  if [[ -n "${E2E_PYTHON:-}" ]]; then
    "${E2E_PYTHON}" "$@"
  elif command -v conda >/dev/null 2>&1; then
    conda run --no-capture-output -n offline-ai python "$@"
  else
    python "$@"
  fi
}

case "${ACTION}" in
  start)
    run_python "${ROOT}/app.py" e2e-setup
    run_python "${ROOT}/app.py" e2e-cleanup
    run_python "${ROOT}/app.py" runserver
    ;;
  cleanup)
    run_python "${ROOT}/app.py" e2e-cleanup
    ;;
  *)
    echo "Usage: $0 {start|cleanup}" >&2
    exit 2
    ;;
esac

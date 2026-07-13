#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ACTION=${1:-start}

export E2E_DATABASE_URL=${E2E_DATABASE_URL:-postgresql+psycopg://offline_ai:offline_ai@127.0.0.1:5432/offline_ai_e2e}
export E2E_DATABASE_ADMIN_URL=${E2E_DATABASE_ADMIN_URL:-postgresql://offline_ai:offline_ai@127.0.0.1:5432/postgres}
export E2E_DOCUMENT_STORAGE_ROOT=${E2E_DOCUMENT_STORAGE_ROOT:-/tmp/offline-intelligence-hub-e2e}
export E2E_DOCUMENT_STORAGE_DIR=${E2E_DOCUMENT_STORAGE_DIR:-${E2E_DOCUMENT_STORAGE_ROOT}/documents}
export DATABASE_URL=${E2E_DATABASE_URL}
export DOCUMENT_STORAGE_DIR=${E2E_DOCUMENT_STORAGE_DIR}
export DOCUMENT_INGESTION_MODE=sync
export LLM_BACKEND=fake
export LLM_WARMUP_ENABLED=false
export LLM_MAX_CONCURRENT_REQUESTS=${E2E_LLM_MAX_CONCURRENT_REQUESTS:-16}
export EMBEDDING_BACKEND=fake
export EMBEDDING_MODEL=fake-bow
export ENVIRONMENT=testing
export HOST=127.0.0.1
export PORT=${E2E_API_PORT:-8002}

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

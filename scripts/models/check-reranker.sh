#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reranker-env.sh"
configure_reranker_env

echo "Checking reranker models at ${RERANKER_BASE_URL}/models"
curl -fsS "${RERANKER_BASE_URL}/models" >/tmp/offline-hub-reranker-models.json
echo "Checking reranking"
curl -fsS -X POST "${RERANKER_BASE_URL}/rerank" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${RERANKER_MODEL}\",\"query\":\"What is a panda?\",\"documents\":[\"A car\",\"A panda is a bear\"],\"top_n\":2,\"normalize\":true}" \
  >/tmp/offline-hub-reranker-check.json
echo "OK reranker endpoint"

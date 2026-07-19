#!/usr/bin/env bash
set -euo pipefail

EXPECTED_REVISION="c198af4dc24f8e0ab8a569a60f931e03a192fd79"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-/home/imroot/tools/llama.cpp}"
IMAGE="${LLAMA_CPP_CUDA_IMAGE:-offline-intelligence-hub-llama-cuda:c198af4d}"

if [[ ! -d "$LLAMA_CPP_DIR/.git" ]]; then
  printf 'Pinned llama.cpp checkout not found: %s\n' "$LLAMA_CPP_DIR" >&2
  exit 2
fi

actual_revision="$(git -C "$LLAMA_CPP_DIR" rev-parse HEAD)"
if [[ "$actual_revision" != "$EXPECTED_REVISION" ]]; then
  printf 'llama.cpp revision mismatch: expected %s, found %s\n' \
    "$EXPECTED_REVISION" "$actual_revision" >&2
  exit 2
fi

if [[ -n "$(git -C "$LLAMA_CPP_DIR" status --porcelain --untracked-files=no)" ]]; then
  printf 'Pinned llama.cpp checkout has tracked modifications: %s\n' "$LLAMA_CPP_DIR" >&2
  exit 2
fi

docker build \
  --file "$LLAMA_CPP_DIR/.devops/cuda.Dockerfile" \
  --target server \
  --build-arg CUDA_VERSION=13.0.2 \
  --build-arg GCC_VERSION=13 \
  --build-arg CUDA_DOCKER_ARCH=120a \
  --build-arg APP_VERSION=9912 \
  --build-arg APP_REVISION="$EXPECTED_REVISION" \
  --tag "$IMAGE" \
  "$LLAMA_CPP_DIR"

printf 'Built pinned llama.cpp CUDA image: %s\n' "$IMAGE"

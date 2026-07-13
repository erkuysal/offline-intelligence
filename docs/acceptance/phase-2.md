# Phase 2 Acceptance Record

Date: 2026-07-10
Status: Complete

## Scope

Phase 2 uses `llama.cpp` through the OpenAI-compatible HTTP adapter. The direct Transformers
adapter is deferred by ADR 0002.

## Automated Gates

- Ruff: passed.
- Mypy: passed for all 43 application modules.
- Test inventory: 73 tests.
- Full PostgreSQL-backed pytest run: 73 passed in 11.00 seconds.
- Rebuilt Docker Compose API test image: passed.
- Full HTTP smoke workflow: passed, including health, PostgreSQL, Redis, LLM readiness,
  Prometheus metrics, auth, chat, document upload, listing, and deletion.

## Real Runtime

Runtime:

- `llama-server` build 9912 (`c198af4dc`)
- `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M`
- CPU execution

Verified:

- Managed server start, health check, and clean stop
- Non-streaming chat completion
- SSE streaming completion and `[DONE]`
- Terminal streaming usage (`16` prompt, `5` completion, `21` total tokens in the wrapper probe)
- Application-level stream cancellation recording
- Application timeout mapping with a deliberately constrained client timeout
- CUDA 13.3 build targeting architecture `120a`
- RTX 5070 detection with 12,226 MiB VRAM
- Full model offload with `-ngl 99` and flash attention
- GPU non-streaming and streaming completions
- GPU streaming usage (`18` prompt, `7` completion, `25` total tokens in the acceptance probe)

Operational notes:

- The default CPU binary remains at `~/tools/llama.cpp/build/bin/llama-server`.
- GPU presets use `~/tools/llama.cpp/build-cuda/bin/llama-server`.
- Test and runtime services were stopped after acceptance; persistent database volumes were
  retained.

## Completion Gate

All Phase 2 completion gates are satisfied. Phase 3 work can proceed from this `v0.2.0`
baseline.

# ADR 0002: Phase 2 LLM Runtime

## Status

Accepted

## Context

Phase 2 requires local instruction-model inference, streaming, cancellation, timeouts,
concurrency limits, token accounting, health checks, and CPU/GPU configuration. The roadmap
originally listed separate Hugging Face Transformers and llama.cpp adapters.

Supporting two in-process runtime stacks would duplicate lifecycle and hardware management at
this stage. It would also couple the API process to model memory use. The existing backend
contract already separates the API from an inference server and is compatible with local
servers that expose the OpenAI chat-completions protocol.

## Decision

- Use `llama.cpp`'s `llama-server` as the supported Phase 2 local inference runtime.
- Integrate inference through the OpenAI-compatible HTTP boundary implemented by `LLMBackend`.
- Keep the fake backend for deterministic development and automated tests.
- Manage model selection, context size, CPU threads, GPU layers, batching, and flash attention
  through the existing runtime configuration and named profiles.
- Defer a direct Hugging Face Transformers adapter until a concrete training, evaluation, or
  model capability cannot be served through the HTTP boundary.
- Keep the backend interface runtime-neutral so another provider can be introduced without
  changing the chat API contract.

## Consequences

- The API and model runtime have separate failure, cancellation, and memory boundaries.
- Quantized GGUF models and CPU/GPU offload remain first-class deployment paths.
- Phase 2 needs one production adapter rather than two partially validated adapters.
- Real-runtime acceptance testing targets `llama-server` and its OpenAI-compatible contract.
- Direct Transformers inference is not a Phase 2 completion requirement; later training and
  evaluation work may revisit the decision.

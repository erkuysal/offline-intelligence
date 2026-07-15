# Technical Vision v1 — Phase 2 Local Model Runtime

Status: Completed

## Intent

Expose local language-model inference through an application-owned contract without coupling the API
to one model server, model family, or hardware configuration.

## System Outcome

- OpenAI-compatible chat completion endpoint
- Non-streaming and server-sent-event streaming responses
- Fake backend for deterministic tests and local OpenAI-compatible runtime for real inference
- Timeouts, cancellation, concurrency limits, prompt and completion limits
- Token accounting, latency metrics, warm-up, readiness, and managed process lifecycle
- Explicit CPU/GPU and model configuration through environment profiles

## Runtime Boundary

```text
API request
   ↓ validation and safety limits
model backend interface
   ├── deterministic fake backend
   └── local OpenAI-compatible server
          ↓
       model artifact
```

The application owns request validation, limits, metrics, error translation, and streaming semantics.
The inference server owns tokenization and model execution. A backend outage must remain a bounded
service failure rather than destabilizing the API process.

## Implemented Function Map

| Function/class | Used for | Why it exists |
| --- | --- | --- |
| `LLMBackend` | Defines health, warm-up, completion, and streaming operations | Keeps API code independent of llama.cpp or any future runtime |
| `FakeLLMBackend` | Deterministic completion and SSE events | Tests transport, persistence, usage, and cancellation without model variability |
| `OpenAICompatibleLLMBackend` | Calls `/models` and `/chat/completions` | Reuses a widely supported local inference protocol |
| `get_llm_backend()` | Selects the configured implementation | Centralizes backend validation and avoids conditional logic in routes |
| `validate_llm_safety_limits()` | Checks total message and requested completion bounds | Rejects oversized work before reserving inference capacity |
| `stream_llm_response()` | Relays SSE, captures content/usage, translates failures | Keeps a stable client stream while retaining server metrics and persistence |
| `LLMReadiness` | Maintains warm-up/readiness state | Avoids expensive or failing warm-up work on every request |
| `estimate_tokens()` | Supplies deterministic fake-backend usage | Provides test accounting only; real runtime usage remains authoritative |

The core implementation is in
[`llm.py`](../../../apps/api/app/services/llm.py) and
[`chat.py`](../../../apps/api/app/api/v1/chat.py).

## Streaming Mechanics

The OpenAI-compatible backend requests `stream=true` and `include_usage=true`, then relays non-empty
SSE lines. The API distinguishes:

- content deltas, appended to the final assistant message;
- a finish chunk, which closes generation semantically;
- a usage chunk, which supplies prompt/completion/total token counts;
- `[DONE]`, which terminates the transport stream.

Client cancellation stops consuming the upstream iterator. Timeouts and unavailable backends are
translated into stable application errors rather than leaking `httpx` exceptions.

## Limits and Calculations

Default safety rails are:

| Limit | Default | Purpose |
| --- | ---: | --- |
| Total message characters | 50,000 | Bounds prompt memory and context use |
| Completion tokens | 2,048 | Bounds runaway generation |
| Concurrent requests | 1 | Prevents CPU/GPU oversubscription on local hardware |
| Request timeout | 60 seconds | Turns runtime stalls into bounded failures |
| Warm-up timeout | 5 seconds | Keeps readiness probing inexpensive |

The fake backend estimates `tokens = max(1, whitespace_word_count)`. This is deliberately not used
as a tokenizer-accurate production metric. For real runs, throughput is later computed from runtime
completion usage:

```text
generation_seconds = last_stream_event_time - first_generation_request_time
tokens_per_second = completion_tokens / generation_seconds
```

Time to first token is measured separately because a high steady-state token rate can conceal slow
prompt evaluation or queueing.

## Why These Choices

- The OpenAI-compatible boundary permits llama.cpp today without embedding its process API into
  FastAPI business logic.
- SSE works over normal HTTP infrastructure and supports incremental UI rendering.
- One concurrency slot is conservative but predictable for local machines; Phase 6 will replace a
  universal guess with measured hardware profiles.
- Model revision metadata is operationally important even when the server exposes the same model
  name, because weights or quantization may differ.

## Completion Evidence

- [Phase 2 runtime ADR](../../adr/0002-phase-2-llm-runtime.md)
- [Phase 2 acceptance](../../acceptance/phase-2.md)
- [Streaming chat contract](../../api/streaming-chat.md)
- [Production model runtime](../../mvp/model-runtime.md)

## Lasting Responsibility

Phases 5 and 6 may change the loaded artifact through adapters and quantization, but they must retain
this stable application boundary and its safety rails.

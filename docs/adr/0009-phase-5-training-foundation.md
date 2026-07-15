# ADR 0009: Phase 5 Training Foundation and Continuity Contract

Date: 2026-07-15
Status: Accepted

## Context

Phase 5 must adapt model behavior without changing the permission-aware RAG boundary or silently
training against a prompt format that differs from production. The accepted runtime is a quantized
Gemma 3 1B GGUF served through llama.cpp, while training requires the Hugging Face BF16 source
checkpoint. Those artifacts need explicit identity, formatting, resource, and behavioral gates.

The exact source tokenizer initially had no cached tokenizer assets. Transformers constructed a
five-token placeholder that mapped Gemma control tokens to `<unk>`. The continuity verifier now
rejects that state instead of allowing empty source generations.

## Decision

- Train from `google/gemma-3-1b-it` revision
  `dcc83ea841ab6100d6b47a070329e1ba4cf78752` under the Gemma Terms of Use.
- Use the isolated `offline-ai-training` environment pinned by `environment.training.yml`.
- Use BF16 LoRA with frozen base weights. The initial rank is 8, alpha is 16, dropout is 0.05, and
  target modules are `q_proj`, `k_proj`, `v_proj`, and `o_proj`.
- Pin the complete 262,144-token tokenizer and control-token IDs 105/106.
- Pin `config/training/gemma3-chat-template.jinja` and fold the production system message into the
  first Gemma `user` turn. This matches Google guidance and the template embedded in the GGUF.
- Preserve `llama-server` as the deployment boundary. The accepted base artifact is Q4_K_M at
  repository commit `61333bac858461ec0c309b7baafdc408d7d2c381`, file SHA-256
  `8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135`.
- Accept source-to-GGUF drift only when both preserve expected facts, grounded refusal, and
  document-instruction isolation. Runtime citation rate must be at least 0.75 and may trail the
  source by no more than 0.25.
- Treat 1,024 tokens as the currently safe training length. The 2,048-token probe completes but its
  13,194.8 MiB peak allocation exceeds the RTX 5070's 12,227 MiB physical capacity; it is not
  approved for sustained training without a separately proven memory strategy.
- Gradient checkpointing is not required by the current one-step LoRA probes and remains disabled.

## Evidence

The five-case deterministic continuity slice passed for English grounding, Turkish grounding,
grounded refusal, document-instruction isolation, and citation formatting. Source citation rate was
1.00; Q4_K_M runtime citation rate was 0.75; measured drift was 0.25.

The pinned environment was independently recreated as `offline-ai-training-repro` from
`environment.training.yml`. Its preflight and local-only template checks passed before the
temporary environment received any CUDA compiler diagnostics, closing the clean-recreation gate.

Continuity was measured with llama.cpp build `b9912-c198af4dc` using its CPU binary because the
then-current CUDA binary reported a CUDA driver/runtime mismatch. This did not alter prompt or
quantization equivalence. The follow-on repair now builds the same llama.cpp revision in the pinned
`offline-ai-llama-build` environment with CUDA 13.0, GCC 13.4, and RTX 5070 architecture `120a`.
The resulting `build-cuda` resolves `libcudart`, `libcublas`, and `libcublasLt` from that environment
through embedded runtime paths; no `LD_LIBRARY_PATH` override is required. It detected the RTX 5070
and loaded the accepted Q4_K_M Gemma artifact for a successful chat-completion smoke request.

## Consequences

- Dataset rendering and adapter evaluation have one reviewable prompt template rather than a
  library default.
- A missing tokenizer cache fails early and actionably.
- Adapter promotion cannot hide citation or refusal drift behind qualitative examples.
- Work Package 5.0 is accepted and Work Package 5.1 may proceed. The first training limit is pinned
  to 1,024 tokens; 2,048 remains unapproved.
- Training data must contain behavior and formatting targets only; private or changing facts remain
  in RAG.

## References

- [Gemma formatting and system instructions](https://ai.google.dev/gemma/docs/core/prompt-structure)
- [Gemma Terms of Use](https://ai.google.dev/gemma/terms)
- [Hugging Face chat templates](https://huggingface.co/docs/transformers/chat_templating)

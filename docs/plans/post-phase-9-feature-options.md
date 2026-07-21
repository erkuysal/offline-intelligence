# Post-Phase-9 Feature Options

Status: Planning catalog — no feature selected or authorized

## Selection Rule

Phase 9 hardening completes before a new feature track is promoted. Candidate work is ranked using:

1. measurable user or operational value;
2. compatibility with offline and authorization boundaries;
3. evaluation method and rollback path;
4. artifact, VRAM, storage, and maintenance cost; and
5. whether the same outcome can be achieved with simpler RAG, prompting, or operations work.

Only one major track should become the next active phase. Small independent improvements may be
scheduled alongside it when they do not alter the release trust boundary.

## Option A: Balanced and Deep Model Tiers

Goal: add measured `fast`, `balanced`, and optionally `deep` local generation profiles.

- Benchmark Gemma 3 4B Q4 at 4K and 8K as the first balanced candidate
- Acquire a 12B candidate only if 4B evidence leaves a clear quality gap
- Define explicit routing, concurrency, VRAM-margin, timeout, and fallback contracts
- Repeat retrieval-grounded quality, refusal, leak, latency, and resource gates per tier

Requires model acquisition and repeated LLM-server runs. Recommended only after release hardening.

## Option B: Fine-Tuning Improvement Cycle

Goal: revisit behavioral adaptation using the Phase 5 post-mortem rather than promoting the failed
adapters.

- Render training prompts through the production context/prompt builders
- Expand unique examples and held-out cells, especially citations, incident reports, JSON, and
  Turkish behavior contracts
- Use step-based optimization, constant-with-warmup scheduling, proportional LoRA alpha, and less
  aggressive clipping experiments
- Separate semantic quality from strict syntax validity and retain four-mode regression gates

Requires GPU training and later real model-server evaluation. It should begin only when a concrete
behavior gap justifies adapter maintenance.

## Option C: Administrative and Governance Workflows

Goal: make existing security and evidence capabilities usable by administrators.

- User/role and document-permission administration
- Audit-log browsing, retention controls, and export
- Retrieval/model evidence inspection and release inventory views
- Backup, restore, system health, and model-status workflows

Most development and tests can use fake backends; final end-to-end acceptance uses both model
servers. This is the strongest product-value candidate after Phase 9.

## Option D: Desktop and Single-Workstation Packaging

Goal: provide a guided local installation and lifecycle for non-container-expert operators.

- Desktop shell or installer around the verified bundle/operator contract
- Hardware preflight, model selection, progress, logs, backup, and update UI
- Preserve checksum/signature verification and keep secrets outside packaged artifacts

Requires OS-specific packaging and substantially broadens the support matrix. It should not bypass
the Phase 9 trust and upgrade contracts.

## Option E: Voice Input

Goal: add fully local Turkish/English speech-to-text before the existing chat path.

- Evaluate Whisper Large v3 Turbo first, then compare full Large v3 only if needed
- Measure word error rate, latency, VRAM contention, and sequential scheduling with the LLM
- Keep audio retention explicit and disabled by default

Requires new model artifacts and server/runtime evaluation. It is lower priority than governance
and balanced-model work.

## Option F: Retrieval and Native Research

Goal: improve measured bottlenecks without changing production behavior speculatively.

- Re-evaluate reranking or query expansion only on larger representative datasets
- Profile contiguous-data production opportunities before adding native kernels or SIMD
- Compare pgvector/index configuration before considering custom vector infrastructure

This is evidence-triggered research, not a standing rewrite project.

## Recommended Order

1. Administrative and governance workflows
2. Gemma 3 4B balanced-model evaluation
3. Fine-tuning improvement cycle when a validated behavior gap exists
4. Desktop packaging
5. Voice input
6. Additional native/retrieval research only after profiling

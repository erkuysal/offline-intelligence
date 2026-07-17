# Phase 5 Acceptance Record

Date: 2026-07-17

Status: **Closed with base-only runtime**

## Accepted

- Pinned training environment, source checkpoint, prompt contract, and CUDA calibration
- Versioned, provenance-aware, leakage-protected training-data contract
- Deterministic bounded LoRA training with adapter-only checkpoints and resumability
- Independent development evaluation and four-mode production evaluation
- Immutable Safetensors/GGUF export and fail-closed opt-in runtime activation
- Adapter identity/checksum diagnostics, rollback, and PEFT/GGUF parity testing
- Checksum-indexed evidence for both accepted infrastructure and rejected model candidates

## Model Decision

Neither trained adapter is promoted. V2 and v3 both failed protected production gates; the accepted
product configuration remains the pinned Gemma 3 1B Q4 base model with permission-aware dense RAG.
The base-only profile is the default, and all adapter profiles remain opt-in negative evidence.

V3 failed 11 final matrix gates spanning citation format, incident structure, terminology, refusal,
protected quality, hallucination, and relative TTFT. The definitive records are:

- `docs/acceptance/phase-5-promotion-v2.md`
- `docs/acceptance/phase-5-promotion-v3.md`
- `docs/post-mortem/run_analysis_2026-07-17_wp5.5.md`
- `docs/post-mortem/run_analysis_2026-07-17_wp5.5_v3.md`

## Deferred

Further dataset design, per-task/language candidate gates, checkpoint-level early stopping, and
adapter promotion are deferred until the initial eight-phase barebones structure is complete. These
items remain requirements for any future adapter, but do not block Phase 6 while the product uses
the accepted base-only runtime.

## Phase Transition

Phase 6 begins from the immutable Q4 base identity and existing production evaluation boundary. Its
barebones scope is defined in `docs/plans/phase-6.md`.

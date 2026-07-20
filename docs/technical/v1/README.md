# Technical Vision v1

This directory describes how Offline Intelligence Hub evolves technically across its delivery
phases. It preserves the intent of completed phases, defines the boundary of the next phase, and
keeps future architecture visible without treating unimplemented ideas as current capabilities.

## Documentation Model

| Document type | Purpose |
| --- | --- |
| Roadmap | Product direction, learning goals, and phase sequence |
| Technical vision | Intended system shape, boundaries, and architectural outcomes |
| Plan | Ordered implementation work and definition of done |
| ADR | A durable technical decision and its consequences |
| Acceptance record | Evidence that an implemented scope met its gates |

The English and Turkish roadmaps remain the high-level source of product direction. These technical
visions refine that direction. When implementation differs from a vision, an ADR and the accepted
implementation take precedence, and the vision should be updated.

## Phase Map

| Phase | Status | Technical outcome |
| --- | --- | --- |
| [1 — Product Foundation](phase-1-product-foundation.md) | Completed | Secure, observable API and persistence foundation |
| [2 — Local Model Runtime](phase-2-local-model-runtime.md) | Completed | Bounded local inference behind a stable chat contract |
| [3 — Document Ingestion and RAG](phase-3-document-rag.md) | Completed | Permission-aware document ingestion and grounded answers |
| [4 — Retrieval and Evaluation](phase-4-retrieval-evaluation.md) | Completed | Measured retrieval strategies and reproducible RAG quality gates |
| [5 — Model Adaptation](phase-5-model-adaptation.md) | Completed | Reproducible LoRA/PEFT infrastructure; adapters rejected and base retained |
| [6 — Inference Optimization](phase-6-inference-optimization.md) | Completed | Accepted, reproducible Q4 CUDA runtime profile and benchmark |
| [7 — Air-Gapped Delivery](phase-7-air-gapped-delivery.md) | Completed | Verified bundle, network-denied operation, and tested recovery |
| [8 — Native Acceleration](phase-8-native-acceleration.md) | Next | Safe, benchmarked C integration with portable fallback |

See [Target Architecture](target-architecture.md) for the intended end state and the constraints
that must remain true across every phase.

Cross-phase technical notes:

- [Dynamic Local Model Selection on the RTX 5070](dynamic-model-selection.md) — proposed fast,
  balanced, and deep inference tiers with projected storage, VRAM, CPU, GPU, routing behavior, and
  a sequential local speech-to-text/LLM voice pipeline

## Status Rules

- **Completed** means acceptance evidence exists for the delivered scope.
- **Next** means it is the next planning and implementation target, not a delivered capability.
- **In progress** means one or more work packages have accepted evidence while later gates remain.
- **Future** records direction only. Interfaces, dependencies, and dates may change after research.
- A phase is promoted to completed only after its plan, tests, measurements, documentation, and
  acceptance record agree.

## Related Entry Points

- [English roadmap](../../roadmap.en.md)
- [Turkish roadmap](../../roadmap.tr.md)
- [Implementation plans](../../plans/)
- [Architecture decisions](../../adr/)
- [Acceptance evidence](../../acceptance/)
- [API contracts](../../api/)

# Phase 4 Retrieval Acceptance

Date: 2026-07-14
Status: Accepted as part of completed Phase 4

## Accepted Runtime Decision

Dense retrieval remains the default. It achieved perfect Recall@5, MRR, and hit rate on the pinned
40-case English/Turkish corpus with low latency. Lexical and reciprocal-rank-fused hybrid strategies
are explicitly selectable and covered by the same authorization contract.

Reranking matched hybrid quality but added substantial latency. Multi-query retrieval preserved
recall but regressed MRR to 0.841 and raised mean latency above 800 ms. Both remain fallback-safe
experimental modes and are not promoted.

## Completed Scope

- Shared dense, lexical, hybrid, reranked, and multi-query contracts
- Owner/share authorization and document filtering at every retrieval stage
- Privacy-controlled retrieval-run diagnostics and retention
- Exact/overlap context deduplication and stable citations
- Pinned bilingual evaluation corpus and versioned strategy reports
- Local llama.cpp lifecycle support for embedding and reranking models
- Bounded inference, candidate, query-variant, context, and time budgets

## Final Generation Gate

The retrieval layer is accepted. The subsequent full RAG generation evaluation passed citation,
faithfulness, hallucination, refusal, authorization, time-to-first-token, end-to-end latency, and
throughput thresholds. See `phase-4-generation-baseline.md` for the final Phase 4 gate.

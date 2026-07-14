# ADR 0007: Optional Multilingual Reranking

Date: 2026-07-14
Status: Accepted

## Decision

Expose reranking as the explicit `reranked` retrieval strategy. It wraps reciprocal-rank-fused
hybrid retrieval, scores at most 20 fused candidates, and returns the requested result limit.
Dense remains the default.

Use `BAAI/bge-reranker-v2-m3` at upstream revision
`b5160aeac3c6c8fe7beaaaf04c9e0142826b58d1`. The model is Apache-2.0, multilingual, and can be
served offline by llama.cpp from the `gpustack/bge-reranker-v2-m3-GGUF:Q4_K_M` conversion.

The HTTP adapter requires one finite score for every input index. Connection errors, rejected
requests, incomplete responses, duplicate indexes, and non-finite scores cause an unchanged hybrid
fallback. Runtime diagnostics record the pinned model, actual server alias, outcome, candidate
count, scores, ranks, and latency.

## Consequences

The mode is useful for future corpora without putting availability at risk, but it is not promoted
for the current corpus. It matched hybrid quality and added roughly 271 ms mean latency. Operators
must explicitly configure the backend and select `reranked` to incur that cost.

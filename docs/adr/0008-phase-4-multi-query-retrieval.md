# ADR 0008: Optional Query Rewriting and Multi-Query Retrieval

Date: 2026-07-14
Status: Accepted

## Decision

Expose query expansion only through the explicit `multi_query` strategy. The original query is
always variant 0. Up to two local-model rewrites may follow, while user identity and document filters
are copied unchanged into every retrieval request.

Use `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M` at revision
`61333bac858461ec0c309b7baafdc408d7d2c381`. Requests allow at most 128 output tokens. Runtime limits
also cap query length, candidate observations, candidates per variant, variant count, and total
pipeline time. Candidate lists are deduplicated by chunk identity and merged with reciprocal rank
fusion.

Malformed output, timeout, connection failure, or a disabled backend falls back to the original
query. Raw original and rewritten queries follow the existing retrieval-run query-text privacy
switch; hashes remain available by default.

## Consequences

The implementation remains available for future evaluation but is not promoted. On the accepted
corpus it preserved recall but regressed MRR and added substantial inference latency. Dense remains
the default strategy.

# ADR 0006: Reciprocal Rank Fusion for Hybrid Retrieval

## Status

Accepted on 14 July 2026. Hybrid is selectable; dense remains the default.

## Decision

Run dense and lexical retrieval independently with the same authorization, readiness, and document
filters. Over-fetch three times the requested final limit from each strategy, bounded by 100
candidates per strategy. Deduplicate by chunk ID and fuse ranks with Reciprocal Rank Fusion:

```text
RRF(chunk) = sum(1 / (60 + strategy_rank))
```

Sort by descending fused score, then best contributing rank and chunk ID for deterministic ties.
Retain each contributing strategy's rank and normalized score on the fused candidate. Dense,
lexical, and hybrid modes are explicitly selectable in chat, direct document search, and retrieval
evaluation requests.

## Rationale

Dense cosine similarity and PostgreSQL lexical rank are not directly comparable. RRF combines their
ordering without premature score calibration and is insensitive to the different score ranges.
Over-fetching gives each strategy room to contribute before the final limit and chunk-level
deduplication prevents duplicate context.

## Default Strategy

The accepted hybrid baseline matched dense retrieval quality exactly and had no per-question recall
or reciprocal-rank regressions, but increased mean latency from 10.4 ms to 21.0 ms. Dense therefore
remains the default. Hybrid can be selected explicitly and will be reconsidered when a broader corpus
shows a material quality gain.

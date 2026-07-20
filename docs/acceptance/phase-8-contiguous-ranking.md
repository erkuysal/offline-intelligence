# Phase 8 WP8.4 Contiguous Ranking Acceptance

Date: 20 July 2026

Status: Accepted for already-contiguous offline evaluation only

## Scope

This gate integrates ABI version `1` into one bounded top-k ranking path over a prepared row-major
float32 matrix. It measures cosine scoring plus sorting/top-k selection. Deterministic matrix
generation is excluded because the intended consumer already owns contiguous buffers.

Production PostgreSQL/pgvector retrieval, authorization, source identity, and runtime application
vectors are unchanged.

## Contract and Result

- Dimensions: 768
- Rows: 4,096
- Top-k: 20
- Prepared input size: 12,585,984 bytes
- Warm-up samples: 2
- Measured samples: 7
- Minimum required speedup: 5.0x
- Maximum allowed score error: `1e-6`

| Implementation | Mean ms | P50 ms | P95 ms |
| --- | ---: | ---: | ---: |
| Python contiguous fallback | 144.371 | 144.197 | 146.395 |
| Native scalar C | 2.625 | 2.621 | 2.673 |

Observed speedup was `54.999856x`. Native and fallback returned identical top-20 row identities;
maximum top-k score error was `1.3259536316145848e-09`. No threshold failed.

## Decision

Accept native ranking only when the caller already owns compatible contiguous float32 buffers.
Reject automatic conversion of the application's nested list embeddings because WP8.3 measured a
0.45–0.69x regression at that boundary. This integration remains offline/experimental and cannot
replace database-native retrieval without a separate architecture and authorization review.

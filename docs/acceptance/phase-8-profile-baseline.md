# Phase 8 WP8.0 Native Profiling Acceptance

Date: 20 July 2026

Status: Accepted for experimental continuation only

## Decision

Proceed with a portable batch-cosine C prototype for offline evaluation and experimental reranking.
Do not replace production dense retrieval: PostgreSQL/pgvector already owns indexed cosine search
and no application-side production similarity bottleneck was found.

## Contract and Environment

- Contract: `config/native/vector-similarity-profile-v1.json`
- Report: `phase-8-profile-baseline.json`
- Candidate: `batch_cosine_f32`
- Warm-up samples: 2
- Measured samples: 7
- Host: AMD Ryzen 9 9950X, 32 logical CPUs, Linux x86-64 under WSL2
- Python: 3.14.6
- Inputs: deterministic non-zero Python float vectors; setup/allocation excluded from timing

## Relevant Outcomes

| Dimensions | Batch | P50 ms | P95 ms | Mean vectors/s |
| ---: | ---: | ---: | ---: | ---: |
| 128 | 1 | 0.006 | 0.006 | 167,124 |
| 128 | 256 | 1.179 | 1.456 | 210,347 |
| 768 | 1 | 0.032 | 0.033 | 30,802 |
| 768 | 32 | 0.783 | 0.815 | 40,832 |
| 768 | 256 | 6.191 | 6.266 | 41,270 |
| 1536 | 32 | 1.534 | 1.541 | 20,895 |

The single-vector measurements show that per-score native calls would mostly expose binding
overhead. The 32- and 256-row workloads are the relevant native boundary because one call can
amortize validation and dispatch across enough arithmetic work.

## Guardrails

- Production retrieval remains unchanged.
- The Python fallback is the correctness oracle and remains available.
- Native promotion requires tolerance tests, sanitizers, boundary-inclusive benchmarks, one bounded
  integration, and measurable end-to-end improvement.
- A microbenchmark speedup alone is insufficient for production activation.

## Verification

Five focused profile/CLI tests passed. Ruff and MyPy passed for the profiling implementation. The
command completed without database, Docker, LLM, embedding, network, or CUDA dependencies.

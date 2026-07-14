# Phase 4 Generation Baseline Acceptance

Date: 2026-07-14
Status: Accepted; Phase 4 complete

## Scope

The full RAG evaluator ran the accepted dense retrieval path and production grounded prompt against
the versioned 20-document, 40-question English/Turkish corpus. It exercised answerable, ambiguous,
unanswerable, and permission-restricted cases while consuming the real streaming response path.

The generator was `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M` at revision
`61333bac858461ec0c309b7baafdc408d7d2c381`. The embedding model and corpus remain pinned by the
dataset manifest. Natural answers were scored deterministically for expected facts, source
citations, cited-claim support, refusal behavior, restricted-fact leaks, time to first token,
end-to-end latency, and token throughput.

## Accepted Result

The checked-in `evaluation/baselines/generation-baseline-v1.json` passed all configured gates:

| Metric | Result | Gate |
| --- | ---: | ---: |
| Parse success | 1.000 | >= 1.000 |
| Expected fact coverage | 0.703 | >= 0.650 |
| Citation accuracy | 0.688 | >= 0.650 |
| Citation coverage | 0.750 | >= 0.700 |
| Answer faithfulness | 0.688 | >= 0.650 |
| Hallucination rate | 0.312 | <= 0.350 |
| Refusal accuracy | 1.000 | >= 1.000 |
| Restricted fact leaks | 0 | <= 0 |
| Mean / P95 time to first token | 407.6 / 511.1 ms | <= 600 / 750 ms |
| Mean / P95 end-to-end latency | 782.7 / 1225.7 ms | <= 1200 / 1600 ms |
| Mean throughput | 25.2 tokens/s | >= 20 tokens/s |

## Decision and Limitations

The result establishes an honest regression floor for the small pinned offline model and completes
the Phase 4 evaluation contract. It is not a production-quality ceiling: some answers omit citations
or switch between English and Turkish, and fact/citation quality remains the clearest target for a
future model or prompt upgrade. Safety behavior was strong in this corpus: every no-result case was
refused and no restricted expected fact appeared in an answer.

Dense remains the runtime retrieval default. Lexical and hybrid remain selectable; reranking and
multi-query remain experimental because their measured cost or ranking regression did not justify
promotion.

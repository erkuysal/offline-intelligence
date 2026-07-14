# Phase 4 Reranked Retrieval Evaluation

Date: 2026-07-14
Status: Implemented and selectable; not promoted
Dataset: `dense-baseline` `1.0.0`
Model: `BAAI/bge-reranker-v2-m3` revision `b5160aeac3c6c8fe7beaaaf04c9e0142826b58d1`
Runtime: llama.cpp, `gpustack/bge-reranker-v2-m3-GGUF:Q4_K_M`

## Results

The versioned report is stored at
[`evaluation/baselines/reranked-baseline-v1.json`](../../evaluation/baselines/reranked-baseline-v1.json).

```text
Recall@5: 1.000
Precision@5: 0.300
Mean Reciprocal Rank: 1.000
Hit rate: 1.000
No-result accuracy: 0.500
Authorization leaks: 0
Mean unique-context ratio: 1.000
Mean relevant-context retention: 1.000
Mean retrieval latency: 292.2 ms
P95 retrieval latency: 485.5 ms
```

## Decision

Reranking exactly matched the accepted hybrid quality metrics, so it provided no measured quality
gain. Its mean latency was about 13.9 times the hybrid baseline and p95 was about 16.9 times higher.
It therefore remains an explicit experimental mode; dense remains the default. The fallback-safe
implementation is retained so the decision can be revisited on a larger or harder corpus.

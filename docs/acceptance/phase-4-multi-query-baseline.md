# Phase 4 Multi-Query Retrieval Evaluation

Date: 2026-07-14
Status: Implemented and selectable; rejected for promotion
Dataset: `dense-baseline` `1.0.0`
Rewrite model: `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M`
Revision: `61333bac858461ec0c309b7baafdc408d7d2c381`

## Results

The rejected versioned report is stored at
[`evaluation/baselines/multi-query-baseline-v1.json`](../../evaluation/baselines/multi-query-baseline-v1.json).

```text
Recall@5: 1.000
Precision@5: 0.300
Mean Reciprocal Rank: 0.841
Hit rate: 1.000
No-result accuracy: 0.500
Authorization leaks: 0
Mean unique-context ratio: 1.000
Mean relevant-context retention: 1.000
Mean retrieval latency: 831.4 ms
P95 retrieval latency: 1319.4 ms
Threshold failure: MRR < 0.950
```

## Decision

Multi-query retrieval did not improve recall or hit rate, reduced MRR by approximately 0.159 from
hybrid, and increased mean latency by roughly 810 ms. It remains an explicit experimental mode with
original-query fallback. Dense remains the runtime default. Further tuning is deferred until a
larger corpus has headroom for recall gains.

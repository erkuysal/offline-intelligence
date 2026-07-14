# Phase 4 Hybrid Retrieval Baseline Acceptance

Date: 2026-07-14
Status: Accepted as an explicit mode; dense remains the default
Dataset: `dense-baseline` `1.0.0`
Fusion: Reciprocal Rank Fusion, `k=60`, 3x per-strategy over-fetch

## Accepted Results

The hybrid strategy was measured with the accepted `embeddinggemma-300m` runtime and PostgreSQL
lexical strategy on the same 20-document, 40-question English/Turkish corpus. The machine-readable
report is stored at
[`evaluation/baselines/hybrid-baseline-v1.json`](../../evaluation/baselines/hybrid-baseline-v1.json).

```text
Recall@5: 1.000
Precision@5: 0.300
Mean Reciprocal Rank: 1.000
Hit rate: 1.000
No-result accuracy: 0.500
Authorization leaks: 0
Mean retrieval latency: 21.0 ms
P95 retrieval latency: 28.8 ms
```

Hybrid had no per-question recall or reciprocal-rank regressions versus dense retrieval. It recovered
the lexical-only miss `en-backup-ambiguous`, but dense already ranked that semantic paraphrase first.
Aggregate hybrid quality therefore equals dense quality while adding approximately 10.6 ms mean
latency in this sample.

## Default Strategy Decision

Dense remains the default because hybrid did not improve an agreed quality metric on this corpus.
Hybrid is accepted as an explicitly selectable runtime and evaluation mode, with per-candidate dense,
lexical, and fused ranks retained for diagnosis. This decision can be revisited when the corpus grows
or contains more exact identifiers and semantic paraphrases in the same query set.

## Regression Thresholds

```text
Recall@5 >= 0.95
Precision@5 >= 0.25
Mean Reciprocal Rank >= 0.95
Hit rate >= 0.95
No-result accuracy >= 0.50
Mean retrieval latency <= 50 ms
P95 retrieval latency <= 50 ms
Authorization leaks = 0
```

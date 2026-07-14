# Phase 4 Lexical Retrieval Baseline Acceptance

Date: 2026-07-14
Status: Accepted
Dataset: `dense-baseline` `1.0.0`
Strategy: PostgreSQL full-text search with the `simple` configuration

## Accepted Results

The lexical strategy was measured on the same 20-document, 40-question English/Turkish corpus as
the accepted dense baseline. The machine-readable report is stored at
[`evaluation/baselines/lexical-baseline-v1.json`](../../evaluation/baselines/lexical-baseline-v1.json).

```text
Recall@5: 0.969
Precision@5: 0.441
Mean Reciprocal Rank: 0.969
Hit rate: 0.969
No-result accuracy: 0.500
Authorization leaks: 0
Mean retrieval latency: 1.4 ms
P95 retrieval latency: 3.1 ms
```

The only relevant miss was `en-backup-ambiguous`: “recurring recovery check” does not share terms
with the relevant “restore drills” passage. Dense retrieval ranks that semantic paraphrase first,
making it a concrete hybrid-fusion test case. Lexical retrieval improved precision over dense
retrieval (`0.441` versus `0.300`) while preserving the same no-result accuracy and authorization
behavior.

## Regression Thresholds

```text
Recall@5 >= 0.95
Precision@5 >= 0.40
Mean Reciprocal Rank >= 0.95
Hit rate >= 0.95
No-result accuracy >= 0.50
Mean retrieval latency <= 50 ms
P95 retrieval latency <= 50 ms
Authorization leaks = 0
```

## Conclusion

The lexical strategy is accepted as an independently selectable evaluation strategy. It is not yet
the production default. Phase 4.3 will compare dense, lexical, and reciprocal-rank-fused results on
this exact corpus before selecting a default.

# Phase 4 Dense Retrieval Baseline Acceptance

Date: 2026-07-14
Status: Accepted
Dataset: `dense-baseline` `1.0.0`

## Scope

The baseline contains 20 documents and 40 questions, split evenly between English and Turkish.
It covers 28 answerable, four ambiguous, four unanswerable, and four permission-restricted cases.
Stable document and passage labels are used instead of database chunk IDs.

The accepted embedding runtime is:

- Repository: `ggml-org/embeddinggemma-300M-qat-q4_0-GGUF`
- Snapshot: `8dd0ca2a66a8f14470acb0e2a71f801afbc5fb73`
- Server alias: `embeddinggemma-300m`
- Dimensions: 768
- Preprocessing: model-server native tokenization with no application-side normalization
- Retrieval: pgvector cosine distance, limit 5

## Accepted Results

The machine-readable report is stored at
[`evaluation/baselines/dense-baseline-v1.json`](../../evaluation/baselines/dense-baseline-v1.json).

```text
Cases: 40 (32 relevant, 8 expected no-result)
Recall@5: 1.000
Precision@5: 0.300
Mean Reciprocal Rank: 1.000
Hit rate: 1.000
No-result accuracy: 0.500
Authorization leaks: 0
Mean retrieval latency: 10.4 ms
P95 retrieval latency: 15.8 ms
```

Every relevant English and Turkish case ranked its expected passage first. All four restricted
document checks returned no candidates. The four genuinely unanswerable questions still returned
nearest-neighbor candidates because dense retrieval does not yet apply a relevance cutoff; this is
why no-result accuracy is 0.500 rather than 1.000.

## Regression Thresholds

The accepted dense-only thresholds are:

```text
Recall@5 >= 0.95
Precision@5 >= 0.25
Mean Reciprocal Rank >= 0.95
Hit rate >= 0.95
No-result accuracy >= 0.50
Mean retrieval latency <= 50 ms
Authorization leaks = 0
```

These thresholds protect the current bilingual ranking and authorization behavior without treating
dense retrieval's unanswerable-query weakness as solved. Hybrid retrieval, calibration, or an
explicit relevance policy should improve no-result accuracy in a later package.

The evaluator's failure behavior was checked with `--min-precision 0.31`. The observed precision
of `0.300` produced a failed summary and process exit status `1`.

## Remaining Evaluation Work

- Add full RAG generation evaluation as a separate stage.
- Measure citation accuracy, context relevance and duplication, faithfulness, and hallucination.
- Record time to first token, end-to-end latency, and generation throughput.
- Compare lexical-only and hybrid retrieval against this exact corpus and report.

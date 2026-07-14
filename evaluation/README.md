# Retrieval Evaluation

Phase 4 evaluation datasets use versioned JSONL records so corpus content, relevance labels, and
runtime metadata can be reviewed and changed together. A dataset contains exactly one `manifest`,
one or more `document` records, and one or more `case` records.

Documents use stable `document_key` and passage `label` values rather than database IDs, which may
change whenever the corpus is recreated or re-chunked. Cases record language, expected answer
facts, relevant passage labels, expected result behavior, category, and optional document filters.
The supported categories are answerable, unanswerable, ambiguous, and permission-restricted.

Run the deterministic dense-retrieval smoke baseline against the isolated test profile:

```bash
./manage.py --env-file config/env/test.env evaluate-retrieval \
  --min-recall 1 \
  --min-hit-rate 1 \
  --min-no-result-accuracy 1
```

The command recreates only its dedicated evaluation users and documents. It does not delete normal
application data. It prints a summary, writes a per-case JSON report under `var/evaluation/`, and
returns a non-zero status when a configured threshold fails. The dataset's embedding model must
match the configured provider unless `--allow-model-mismatch` is explicitly selected for an
experiment.

The included smoke corpus proves the runner, pgvector query, filtering, and metric contracts. It is
not the accepted real-model dense baseline.

Run the accepted 20-document, 40-question real-model baseline with:

```bash
./manage.py evaluate-retrieval \
  --dataset evaluation/datasets/dense-baseline-v1.jsonl \
  --limit 5 \
  --min-recall 0.95 \
  --min-precision 0.25 \
  --min-mrr 0.95 \
  --min-hit-rate 0.95 \
  --min-no-result-accuracy 0.5 \
  --max-mean-latency-ms 50 \
  --max-p95-latency-ms 50 \
  --max-authorization-leaks 0 \
  --output evaluation/baselines/dense-baseline-v1.json
```

The checked-in [baseline report](baselines/dense-baseline-v1.json) records the accepted metrics and
per-question rankings. See the [acceptance record](../docs/acceptance/phase-4-dense-baseline.md) for
interpretation and known limitations.

Evaluation reports also apply the runtime context selector to retrieved candidates and report mean
unique-context ratio plus mean relevant-context retention. Passage text and source offsets are used
only in memory for this calculation and are excluded from the JSON report. See the
[context-selection acceptance record](../docs/acceptance/phase-4-context-selection.md).

Run the lexical strategy against the same corpus without an embedding server:

```bash
./manage.py evaluate-retrieval \
  --strategy lexical \
  --dataset evaluation/datasets/dense-baseline-v1.jsonl \
  --limit 5 \
  --min-recall 0.95 \
  --min-precision 0.40 \
  --min-mrr 0.95 \
  --min-hit-rate 0.95 \
  --min-no-result-accuracy 0.5 \
  --max-mean-latency-ms 50 \
  --max-p95-latency-ms 50 \
  --max-authorization-leaks 0 \
  --output evaluation/baselines/lexical-baseline-v1.json
```

The checked-in [lexical baseline report](baselines/lexical-baseline-v1.json) records the accepted
quality, latency, and authorization thresholds. PostgreSQL uses the language-neutral `simple`
configuration documented in [`ADR 0005`](../docs/adr/0005-phase-4-lexical-search.md).

Run the accepted reciprocal-rank-fused hybrid baseline with the real embedding runtime:

```bash
./manage.py evaluate-retrieval \
  --strategy hybrid \
  --dataset evaluation/datasets/dense-baseline-v1.jsonl \
  --limit 5 \
  --min-recall 0.95 \
  --min-precision 0.25 \
  --min-mrr 0.95 \
  --min-hit-rate 0.95 \
  --min-no-result-accuracy 0.5 \
  --max-mean-latency-ms 50 \
  --max-p95-latency-ms 50 \
  --max-authorization-leaks 0 \
  --output evaluation/baselines/hybrid-baseline-v1.json
```

The checked-in [hybrid baseline report](baselines/hybrid-baseline-v1.json) retains dense, lexical,
and fused rank diagnostics. Dense remains the runtime default because hybrid matched dense quality
with higher latency; see the
[hybrid acceptance record](../docs/acceptance/phase-4-hybrid-baseline.md).

Run the optional reranker over a bounded hybrid pool with both local model services active:

```bash
./manage.py evaluate-retrieval \
  --strategy reranked \
  --dataset evaluation/datasets/dense-baseline-v1.jsonl \
  --limit 5 \
  --output evaluation/baselines/reranked-baseline-v1.json
```

The [reranked report](baselines/reranked-baseline-v1.json) matched hybrid quality but incurred much
higher latency, so it is selectable but not promoted. See the
[acceptance record](../docs/acceptance/phase-4-reranked-baseline.md).

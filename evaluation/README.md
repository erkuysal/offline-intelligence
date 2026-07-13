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
  --max-authorization-leaks 0 \
  --output evaluation/baselines/dense-baseline-v1.json
```

The checked-in [baseline report](baselines/dense-baseline-v1.json) records the accepted metrics and
per-question rankings. See the [acceptance record](../docs/acceptance/phase-4-dense-baseline.md) for
interpretation and known limitations.

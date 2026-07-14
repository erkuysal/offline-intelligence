# Retrieval Observability

Each chat retrieval and direct document search can create a `retrieval_runs` diagnostic record.
The record captures the request kind, strategy, embedding model, filters, ranked candidate
identities and scores, selected context identities, outcome, candidate counts, stage timings, and
expiry. Chat runs also record context-selection counts, removed duplicate and overlap volume,
considered/unique/selected character counts, and unique-context ratio. Evaluation runs continue to
use their versioned JSON reports instead of populating this operational table.

Reranked runs add the pinned reranker revision, actual server model alias, bounded candidate count,
success/fallback outcome, reranker latency, and per-candidate hybrid/reranker ranks and scores. A
fallback run retains hybrid candidate strategy metadata so it is distinguishable from a successful
reorder without persisting raw text.

## Privacy Defaults

Raw query and passage text are disabled by default. The query is represented by a SHA-256 digest;
candidate and selected-context records retain document/chunk identity, source metadata, ranks, and
scores without passage content. Operators can explicitly change this behavior when diagnostics
require text, after reviewing the data-retention and access implications:

```env
RETRIEVAL_RUN_PERSISTENCE_ENABLED=true
RETRIEVAL_RUN_PERSIST_QUERY_TEXT=false
RETRIEVAL_RUN_PERSIST_PASSAGE_TEXT=false
RETRIEVAL_RUN_RETENTION_DAYS=30
```

Persistence is best-effort. A diagnostic write failure is recorded in metrics and rolled back, but
does not turn a successful retrieval into a failed user request.

## Metrics and Timings

Prometheus operation metrics expose query embedding, candidate retrieval, context selection,
exact/overlap deduplication, and diagnostic persistence outcomes, durations, and item counts. Each
stored run also includes millisecond timings for the applicable stages. Chat runs include total
pipeline and context-selection timings; direct document searches stop after candidate retrieval.

## Retention

Every record receives an `expires_at` timestamp from `RETRIEVAL_RUN_RETENTION_DAYS`. Delete expired
records with:

```bash
./manage.py retrieval-cleanup
```

Run this command periodically from the deployment scheduler. Deleting a user cascades to that
user's retrieval diagnostics.

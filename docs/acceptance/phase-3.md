# Phase 3 Acceptance Record

Date: 2026-07-10
Version: 0.3.0

## Scope

Phase 3 turns the Phase 2 local LLM runtime into a document RAG backend with database-native retrieval and durable operational state.

Completed capabilities:

- `pgvector` storage with `vector(768)` embeddings and HNSW cosine index
- SQL-ranked retrieval with fixed-dimension validation
- Redis-backed document ingestion worker mode
- TXT, PDF, Markdown, and DOCX ingestion
- cleaned, token-boundary chunking with `source_page` / `source_label` metadata
- duplicate upload rejection and document version history
- stale-only embedding reindex path
- document read permissions and permission-aware retrieval
- non-streaming conversation, message, and source persistence

## Verification

Static checks:

```bash
conda run -n offline-ai python -m ruff check .
conda run -n offline-ai python -m mypy apps/api/app
git diff --check
```

Result: passed.

Focused checks run during implementation:

```bash
conda run -n offline-ai python ./manage.py test -- apps/api/tests/test_documents.py -q
conda run -n offline-ai python ./manage.py test -- apps/api/tests/test_chat.py -q
conda run -n offline-ai python ./manage.py test -- apps/api/tests/test_documents.py apps/api/tests/test_chat.py -q
```

Result: passed after applying migrations through `20260710_0008`.

Container verification:

```bash
docker compose -f deploy/compose.yaml build api-tests
docker compose -f deploy/compose.yaml run --rm api-tests
```

Result: `91 passed`.

Worker smoke:

```bash
conda run -n offline-ai python ./manage.py ingestion-worker --once
```

Result: worker connected to Redis and exited cleanly with no queued job.

## Known Limits

- Streaming chat responses still emit retrieval sources, but only non-streaming completions persist conversation/message/source history in this release.
- DOCX extraction uses document paragraphs and heading styles; it does not preserve page numbers.
- Chunk token boundaries are approximate and derived from whitespace spans, not a model-specific tokenizer.

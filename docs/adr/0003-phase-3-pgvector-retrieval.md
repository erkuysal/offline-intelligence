# ADR 0003: Phase 3 pgvector Retrieval

## Status

Accepted

## Context

Phase 2 stored chunk embeddings as JSON text and ranked search results in Python. That was useful for proving the ingestion and RAG flow, but it does not scale and cannot use database-native vector indexes.

EmbeddingGemma produces 768-dimensional embeddings, so Phase 3 standardizes the document chunk vector shape on `vector(768)`.

## Decision

Store document chunk embeddings in PostgreSQL with the pgvector extension:

- Use `pgvector/pgvector:0.8.2-pg16` for local PostgreSQL.
- Use `pgvector==0.5.0` for SQLAlchemy vector types and distance expressions.
- Replace `embedding_json` with `embedding vector(768)`.
- Add an HNSW cosine index on `document_chunks.embedding`.
- Rank retrieval in SQL with cosine distance and return `1 - distance` as the search score.
- Validate all generated vectors against the fixed 768-dimensional schema before writing or searching.

The migration backfills existing JSON embeddings only when they already match 768 dimensions. Incompatible old embeddings are treated as stale by clearing `embedding_model`; operators should run `./app.py embedding-reindex` after selecting the intended embedding backend.

## Consequences

Search now uses database-native vector ranking and can scale beyond in-process scoring. The schema intentionally rejects mixed vector dimensions, which keeps retrieval predictable when switching from the fake provider to EmbeddingGemma.

The local database image is no longer plain `postgres:16-alpine`; deployments need pgvector support before running migrations.

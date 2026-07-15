# Technical Vision v1 — Phase 3 Document Ingestion and RAG

Status: Completed

## Intent

Turn the local model runtime into a permission-aware knowledge system. Uploaded content becomes
searchable context, while document ownership and sharing rules remain effective through ingestion,
retrieval, generation, citation persistence, and later inspection.

## Data Flow

```text
Upload
  ↓ type and size validation
Extraction
  ↓
Source-aware chunking
  ↓
Embedding
  ↓
PostgreSQL + pgvector
  ↓ authorized retrieval
Context construction
  ↓
Grounded model prompt
  ↓
Answer + persisted citations
```

## System Outcome

- TXT, PDF, Markdown, and DOCX ingestion
- Persisted source offsets, chunks, and embeddings
- Dense similarity search through pgvector
- Owner, shared-reader, readiness, embedding-model, and document filters
- Grounded chat with stable citation numbering
- Conversation history and inspectable source metadata
- Deterministic fake-provider tests plus real local-model acceptance

## Architectural Boundaries

- Ingestion failure does not expose partially ready documents to retrieval.
- Permission filtering occurs inside retrieval, before results enter the prompt.
- Source identity survives chunking and answer persistence.
- The model is instructed from retrieved context; it does not become the authorization boundary.

## Implemented Function Map

| Stage | Main functions/classes | Used for and why |
| --- | --- | --- |
| Storage | `store_upload()` | Streams bytes, enforces maximum size, and calculates SHA-256 before ingestion |
| Extraction | `extract_text()` plus format-specific extractors | Produces one normalized text/source-span contract across TXT, PDF, Markdown, and DOCX |
| Cleaning | `clean_extracted_text()`, `collapse_blank_lines()` | Stabilizes whitespace while retaining source-relative character positions |
| Chunking | `chunk_text()`, `find_source_span()` | Creates overlapping chunks and assigns the best page/heading provenance |
| Ingestion | `ingest_document()`, `process_document_ingestion()` | Replaces chunk state atomically and moves the document through processing/ready/failed states |
| Queueing | `enqueue_document_ingestion()`, `reserve_document_ingestion()`, `acknowledge_document_ingestion()` | Supports recoverable Redis-backed background work while PostgreSQL stays authoritative |
| Embeddings | `EmbeddingProvider`, `embed_document_chunks()`, `validate_embeddings()` | Hides provider details and rejects wrong-sized or non-finite vectors |
| Retrieval | `DenseRetrievalStrategy.retrieve()` | Embeds the query and performs authorization-filtered cosine search in PostgreSQL |
| RAG assembly | `augment_chat_request()`, `build_context()` | Adds grounded instructions and returns selected sources for answer persistence |

See
[`document_ingestion.py`](../../../apps/api/app/services/document_ingestion.py),
[`embeddings.py`](../../../apps/api/app/services/embeddings.py), and
[`rag.py`](../../../apps/api/app/services/rag.py).

## Chunking Calculations

The configured character budget is converted to an approximate token window using four characters
per token:

```text
max_tokens = max(1, floor(chunk_size_chars / 4))
overlap_tokens = min(floor(overlap_chars / 4), max_tokens - 1)
next_start = max(previous_end - overlap_tokens, previous_start + 1)
```

With the defaults, `chunk_size_chars=2000` gives approximately 500 tokens and
`overlap_chars=200` gives approximately 50 overlapping tokens. The `previous_start + 1` term proves
forward progress even under unusual limits. Exact source character offsets are stored with each
chunk so overlap can later be removed without fuzzy text matching.

The standalone storage estimate is:

```text
estimated_tokens = ceil(character_count / 4)
```

This approximation is used for planning, not for billing or model-specific context enforcement.

## Embedding and Retrieval Calculations

The fake embedding provider hashes each normalized token into one of 768 dimensions and increments
that bucket. It then applies L2 normalization:

```text
norm(v) = sqrt(sum(v_i²))
normalized_i = v_i / norm(v)
```

It is deterministic test infrastructure, not a semantic model. The real provider returns vectors
from the pinned embedding runtime; `validate_embeddings()` checks vector count, 768 dimensions, and
finite numeric values before persistence.

Dense retrieval uses pgvector cosine distance:

```text
cosine_similarity(q, d) = (q · d) / (||q|| × ||d||)
cosine_distance = 1 - cosine_similarity
public_normalized_score = 1 - cosine_distance
```

Rows are ordered by ascending distance. The SQL query requires a ready document, a matching embedding
model, a non-null vector, and either ownership or an explicit read permission. Optional document IDs
are applied in the same query, so unauthorized candidates never reach Python ranking or prompts.

## Context and Prompt Contract

Phase 3 initially retrieves up to five chunks and limits context to 12,000 characters. Each context
section carries a stable label such as `[Source 1: file, chunk 3]`. The system instruction tells the
model to answer only when accessible context supports the answer, refuse otherwise, cite factual
answers, and ignore instructions embedded inside documents.

This separation is deliberate: retrieval determines accessible evidence, the prompt communicates
behavior, and persistence records which selected chunks were actually exposed to generation.

## Completion Evidence

- [Phase 3 pgvector ADR](../../adr/0003-phase-3-pgvector-retrieval.md)
- [Phase 3 acceptance](../../acceptance/phase-3.md)
- [Conversation API](../../api/conversations.md)
- [v0.4.0 integrated acceptance](../../acceptance/v0.4.0.md)

## Lasting Responsibility

RAG remains the home of mutable organizational knowledge. Fine-tuning in Phase 5 must improve model
behavior without embedding protected document contents into adapter weights.

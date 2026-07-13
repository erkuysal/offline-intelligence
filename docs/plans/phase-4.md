# Phase 4 Hybrid Retrieval and Evaluation Plan

## Entry Criteria

Phase 4 begins after the `v0.4.0` browser MVP is accepted. Before retrieval behavior changes:

- [x] The upload, ingestion, grounded chat, and source-inspection loop works end to end
- [x] Streaming chat and source persistence have stable contracts
- [x] The E2E environment can create and clean up deterministic corpora
- [x] Retrieval authorization and document filters have regression coverage
- [x] Real embedding model name, dimensions, and preprocessing are pinned
- [x] The supported evaluation languages and initial corpus size are documented

Entry was accepted with `v0.4.0` on 2026-07-13. The pinned dense baseline uses
`ggml-org/embeddinggemma-300M-qat-q4_0-GGUF` snapshot
`8dd0ca2a66a8f14470acb0e2a71f801afbc5fb73`, 768 output dimensions, and the model server's
native tokenization without additional application-side text normalization. The initial
evaluation target is English and Turkish, with 20 representative documents and at least 40
questions spanning answerable, unanswerable, ambiguous, and permission-restricted cases.

## Current Baseline

Already available from Phase 3:

- [x] `pgvector` dense retrieval with cosine distance
- [x] HNSW cosine index on 768-dimensional embeddings
- [x] Ready-document, embedding-model, owner, permission, and document ID filters
- [x] Configurable retrieval limit and context character budget
- [x] Source citations with document and chunk identifiers

Missing for Phase 4:

- [ ] PostgreSQL full-text indexing and lexical search
- [ ] A common retrieval-candidate contract across dense, lexical, and hybrid strategies
- [ ] Score fusion and calibration
- [ ] Reranking
- [ ] Query rewriting and multi-query retrieval
- [ ] Context deduplication
- [ ] Retrieval-run persistence and stage-level observability
- [ ] Full RAG generation evaluation with citation, faithfulness, hallucination, and streaming metrics

## Work Package 4.0: Evaluation Contract and Dense Baseline

This package must precede retrieval changes.

### Dataset

- [x] Define a versioned JSONL evaluation schema
- [x] Include question, expected answer facts, relevant document IDs, and relevant passage labels
- [x] Include answerable, unanswerable, ambiguous, and permission-restricted questions
- [x] Include English and Turkish cases if both are product requirements
- [x] Avoid relying only on database chunk IDs because re-chunking can change them
- [x] Record corpus, chunking, embedding, prompt, model, and evaluator versions

### Runner

- [x] Add a CLI that creates or loads the evaluation corpus
- [x] Run retrieval independently from generation
- [ ] Run full RAG evaluation as a separate stage
- [x] Emit machine-readable JSON and a human-readable summary
- [x] Save per-question results for regression diagnosis
- [x] Support deterministic fake-provider tests and opt-in real-model acceptance

### Baseline Metrics

- [x] Recall@k
- [x] Precision@k
- [x] Mean Reciprocal Rank
- [x] Hit rate and no-result rate
- [ ] Citation document and passage accuracy
- [x] Retrieval latency and candidate count
- [ ] Context relevance and duplication rate
- [ ] Answer faithfulness and hallucination rate
- [ ] Time to first token, end-to-end latency, and tokens per second

### Exit Criteria

- [x] Store an accepted dense-only baseline report
- [x] Define minimum quality thresholds and maximum regression tolerances
- [x] Make failed thresholds produce a non-zero CLI exit code

## Work Package 4.1: Retrieval Architecture and Observability

### Backend

- [ ] Extract dense search behind a retrieval strategy interface
- [ ] Define a candidate containing chunk identity, source, raw score, normalized score, rank, and strategy
- [ ] Keep authorization and metadata filters inside every retrieval query
- [ ] Separate candidate retrieval, fusion, reranking, deduplication, and context construction stages
- [ ] Make strategy and stage limits configurable
- [ ] Preserve stable source ordering and citation numbering

### Persistence and Metrics

- [ ] Add the planned `retrieval_runs` model and migration
- [ ] Record query, strategy, filters, model versions, candidates, selected context, and timings
- [ ] Avoid persisting sensitive query or passage text unless explicitly configured
- [ ] Add Prometheus metrics for each retrieval stage, outcome, latency, and candidate count
- [ ] Add retention or cleanup behavior for retrieval-run records

### Verification

- [ ] Prove owner and permission isolation for every strategy
- [ ] Prove document filters are applied before ranking
- [ ] Add query-count and performance regression tests on a representative corpus

## Work Package 4.2: PostgreSQL Full-Text Search

### Schema and Query

- [ ] Choose language configuration behavior for English, Turkish, and mixed documents
- [ ] Add a generated or maintained `tsvector` representation for chunk content
- [ ] Add an appropriate GIN index
- [ ] Implement safe `websearch_to_tsquery` or equivalent query construction
- [ ] Return lexical rank through the common candidate contract
- [ ] Preserve the same authorization, readiness, model, and document filters as dense search

### Verification

- [ ] Cover exact terms, identifiers, acronyms, filenames, and phrases that dense retrieval may miss
- [ ] Cover punctuation, empty queries, stop words, and malformed input
- [ ] Measure lexical-only quality and latency against the dense baseline

## Work Package 4.3: Hybrid Fusion

### Backend

- [ ] Over-fetch dense and lexical candidates independently
- [ ] Choose Reciprocal Rank Fusion as the initial score-independent baseline
- [ ] Deduplicate candidates by chunk identity before final selection
- [ ] Expose dense rank, lexical rank, fused rank, and strategy metadata for diagnosis
- [ ] Make dense, lexical, and hybrid modes explicitly selectable

### Evaluation

- [ ] Compare dense-only, lexical-only, and hybrid results on the same dataset
- [ ] Accept hybrid as the default only when it improves agreed quality metrics without unacceptable latency
- [ ] Record queries where hybrid regresses so the failure mode remains visible

## Work Package 4.4: Context Selection and Deduplication

- [ ] Detect exact duplicate chunks
- [ ] Reduce overlapping adjacent chunks from the same document
- [ ] Enforce per-document and total context budgets
- [ ] Preserve enough neighboring context for comprehension
- [ ] Measure unique-context ratio and relevant-context retention
- [ ] Keep citation numbering consistent after deduplication

## Work Package 4.5: Reranking

Reranking is optional until hybrid retrieval has a measured baseline.

- [ ] Define a local reranker adapter and failure contract
- [ ] Select and pin an offline-capable multilingual reranker if required
- [ ] Rerank only a bounded candidate set
- [ ] Record reranker model, scores, latency, and fallback outcome
- [ ] Fall back to fused ranking when the reranker is unavailable
- [ ] Accept reranking only when quality gain justifies CPU/GPU and latency cost

## Work Package 4.6: Query Rewriting and Multi-Query Retrieval

These are the final Phase 4 retrieval features because they add inference cost and variability.

- [ ] Define when rewriting is allowed and when the original query must be preserved
- [ ] Prevent rewritten queries from weakening authorization or document filters
- [ ] Limit query variants, total candidates, time, and token usage
- [ ] Merge and deduplicate candidates across variants
- [ ] Persist original and rewritten queries only under the retrieval-run privacy policy
- [ ] Fall back to the original query on timeout or model failure
- [ ] Accept the feature only when evaluation shows a material improvement

## Phase 4 Definition of Done

- [ ] Dense, lexical, and hybrid modes are implemented behind one retrieval contract
- [ ] The default strategy is selected from recorded evaluation evidence
- [ ] Reranking and query expansion are enabled only if they pass quality and latency thresholds
- [ ] Authorization and metadata filtering pass for every strategy and stage
- [ ] Evaluation reports are reproducible from pinned corpus and runtime configuration
- [ ] Retrieval-run diagnostics and Prometheus metrics cover the full pipeline
- [ ] Citation, faithfulness, hallucination, and performance metrics meet accepted thresholds
- [ ] English and Turkish roadmaps and a Phase 4 acceptance record are updated

## Explicit Non-Requirements

The following should not block Phase 4:

- LoRA or PEFT training
- Quantization comparison work
- Desktop packaging
- Air-gapped release bundling
- High-availability deployment

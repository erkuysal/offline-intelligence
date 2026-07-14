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

- [x] Extract dense search behind a retrieval strategy interface
- [x] Define a candidate containing chunk identity, source, raw score, normalized score, rank, and strategy
- [x] Keep authorization and metadata filters inside every implemented retrieval query
- [ ] Separate fusion, reranking, deduplication, and context construction into explicit stages
- [x] Make implemented strategy and stage limits configurable
- [x] Preserve stable source ordering and citation numbering

### Persistence and Metrics

- [x] Add the planned `retrieval_runs` model and migration
- [x] Record query identity, strategy, filters, model versions, candidates, selected context, and timings
- [x] Avoid persisting sensitive query or passage text unless explicitly configured
- [x] Add Prometheus metrics for candidate retrieval, context selection, persistence outcomes, latency, and counts
- [x] Add retention and cleanup behavior for retrieval-run records

### Verification

- [x] Prove owner and permission isolation for every implemented strategy
- [x] Prove document filters are applied before ranking
- [x] Add query-count and performance regression tests on a representative corpus

The dense-strategy integration gate covers owner, shared-reader, outsider, pre-ranking document
filters, and a single-SQL-query limit. Its SQL contract, source ordering, and accepted 20-document
mean/P95 latency gates pass. The dense and lexical live PostgreSQL integration gates were accepted
on 14 July 2026.

## Work Package 4.2: PostgreSQL Full-Text Search

### Schema and Query

- [x] Choose language configuration behavior for English, Turkish, and mixed documents
- [x] Add generated `tsvector` representations for chunk content and document filenames
- [x] Add appropriate GIN indexes
- [x] Implement safe `websearch_to_tsquery` query construction
- [x] Return lexical rank through the common candidate contract
- [x] Preserve the same authorization, readiness, and document filters as dense search

### Verification

- [x] Cover exact terms, identifiers, acronyms, filenames, and phrases that dense retrieval may miss
- [x] Cover punctuation, empty queries, stop words, and malformed input
- [x] Measure lexical-only quality and latency against the dense baseline

The initial lexical baseline uses PostgreSQL's language-neutral `simple` configuration; see ADR
0005. Its live authorization, edge-case, query-count, and bilingual corpus evaluation gates passed
on PostgreSQL on 14 July 2026. Results and thresholds are recorded in the lexical baseline acceptance
record.

## Work Package 4.3: Hybrid Fusion

### Backend

- [x] Over-fetch dense and lexical candidates independently
- [x] Choose Reciprocal Rank Fusion as the initial score-independent baseline
- [x] Deduplicate candidates by chunk identity before final selection
- [x] Expose dense rank, lexical rank, fused rank, and strategy metadata for diagnosis
- [x] Make dense, lexical, and hybrid modes explicitly selectable

### Evaluation

- [x] Compare dense-only, lexical-only, and hybrid results on the same dataset
- [x] Keep dense as the default because hybrid did not improve an agreed quality metric
- [x] Record hybrid regressions and lexical recoveries; no dense regressions were observed

## Work Package 4.4: Context Selection and Deduplication

- [x] Detect exact duplicate chunks
- [x] Reduce overlapping adjacent chunks from the same document
- [x] Enforce per-document and total context budgets
- [x] Preserve enough neighboring context for comprehension
- [x] Measure unique-context ratio and relevant-context retention
- [x] Keep citation numbering consistent after deduplication

## Work Package 4.5: Reranking

Reranking is optional until hybrid retrieval has a measured baseline.

- [x] Define a local reranker adapter and failure contract
- [x] Select and pin an offline-capable multilingual reranker if required
- [x] Rerank only a bounded candidate set
- [x] Record reranker model, scores, latency, and fallback outcome
- [x] Fall back to fused ranking when the reranker is unavailable
- [x] Accept reranking only when quality gain justifies CPU/GPU and latency cost; the measured mode was not promoted

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

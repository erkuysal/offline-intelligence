# Technical Vision v1 — Phase 4 Retrieval and Evaluation

Status: Completed and accepted on 2026-07-14

## Intent

Replace intuition about RAG quality with reproducible evidence. Retrieval variants and generation
behavior are measured on the same pinned bilingual corpus, and optional complexity is promoted only
when it improves an agreed metric within latency and safety limits.

## System Outcome

- Shared candidate contract for dense, lexical, hybrid, reranked, and multi-query strategies
- PostgreSQL full-text search and reciprocal-rank fusion
- Exact and overlap-aware context deduplication with stable citation ordering
- Optional bounded reranking and query rewriting with safe fallbacks
- Privacy-controlled retrieval-run diagnostics and Prometheus stage metrics
- Versioned English/Turkish dataset with 20 documents and 40 questions
- Retrieval and full generation evaluators with non-zero failure exits
- Pinned machine-readable baseline reports

## Runtime Decision

Dense retrieval remains the default. Lexical and hybrid are selectable. Reranking and multi-query
remain experimental because their measured quality/cost trade-offs did not justify promotion.

The accepted generation baseline establishes a regression floor for fact coverage, citations,
faithfulness, hallucination, refusal, restricted-information safety, streaming latency, and
throughput. It identifies citation consistency and factual completeness as Phase 5 improvement
targets.

## Implemented Strategy and Function Map

| Area | Main functions/classes | Used for and why |
| --- | --- | --- |
| Shared contract | `RetrievalQuery`, `RetrievalCandidate`, `RetrievalResult` | Carries identity, filters, scores, provenance, timing, and diagnostics consistently |
| Strategy selection | `build_retrieval_strategy()` | Builds only explicitly configured pipelines and keeps dense as the default |
| Dense | `DenseRetrievalStrategy.retrieve()` | Semantic similarity over authorized pgvector rows |
| Lexical | `LexicalRetrievalStrategy.retrieve()` | Recovers exact terms, identifiers, filenames, and phrases through PostgreSQL FTS |
| Hybrid | `reciprocal_rank_fusion()` | Combines rank order without pretending dense and lexical raw scores share a scale |
| Reranking | `rerank_candidates()` | Reorders a bounded hybrid pool with a local relevance model and fallback |
| Multi-query | `normalize_query_variants()`, `merge_query_results()` | Expands ambiguous wording within query/count/time budgets and preserves the original query |
| Context | `select_context()`, `subtract_intervals()`, `merge_intervals()` | Removes exact/positional duplication and enforces total/per-document budgets |
| Diagnostics | `persist_retrieval_run()`, `record_retrieval_stage()` | Records hashes, model versions, candidate metadata, outcomes, and timings under privacy controls |
| Retrieval evaluation | `evaluate_case()`, `aggregate_metrics()`, `threshold_failures()` | Scores rankings and returns failure status when regression gates are missed |
| Generation evaluation | `collect_stream()`, `score_generated_answer()`, `aggregate_generation_metrics()` | Scores natural answers and measures the actual streaming path |

Source modules are under
[`retrieval/`](../../../apps/api/app/retrieval/) and
[`evaluation/`](../../../apps/api/app/evaluation/).

## Retrieval Calculations

For expected relevant set `R`, returned top-`k` set `A`, and the first relevant rank `r`:

```text
Recall@k = |A ∩ R| / |R|
Precision@k = |A ∩ R| / |A|
ReciprocalRank = 1 / r               (0 if no relevant result)
Hit@k = 1 when |A ∩ R| > 0, else 0
MRR = mean(ReciprocalRank across relevant cases)
```

No-result accuracy is the fraction of cases labeled `no_result` that return no candidate. An
authorization leak is counted whenever a result exposes a document outside the evaluation user's
owner/read permission set; the accepted maximum is always zero.

### Lexical normalization

PostgreSQL `ts_rank_cd` produces a non-negative rank. The implementation maps it into `[0, 1)`:

```text
normalized_lexical_score = raw_rank / (1 + raw_rank)
```

The `simple` text-search configuration avoids language-specific stemming differences across English
and Turkish. Plain token sequences are joined with `OR` so a partial exact-term match can contribute;
explicit quoted or Boolean queries retain their operator meaning.

### Reciprocal-rank fusion

For a chunk appearing at rank `r_s` in strategy `s`:

```text
RRF(chunk) = sum over strategies s of 1 / (k + r_s)
```

The implementation uses `k=60`. With two strategies, the theoretical best score is
`2 / (60 + 1)`, used to normalize hybrid results. Fusion deduplicates by chunk ID and breaks ties by
best component rank, then chunk ID for deterministic output. Hybrid over-fetches
`min(requested_limit × 3, 100)` candidates from each component before returning the requested limit.

### Reranker normalization

Scores already in `[0,1]` are retained. Other finite logits are mapped through a bounded sigmoid:

```text
normalized = 1 / (1 + exp(-clamp(score, -700, 700)))
```

Clamping prevents floating-point overflow. The reranker sees at most 20 candidates by default; a
provider error or wrong score count returns the original hybrid order.

### Multi-query bounds

The original query is always variant zero. Generated variants are whitespace-normalized,
case-insensitively deduplicated, and rejected when longer than 500 characters. Defaults allow two
generated variants, ten candidates per variant, thirty candidate observations total, and 2,000 ms
for the pipeline. Results use RRF across query variants and normalize by the maximum observed fused
score. A rewrite failure falls back to the original query without weakening identity or filters.

## Context Calculations

Context selection tracks already covered source-coordinate intervals per document. For candidate
interval `C` and covered union `U`:

```text
new_segments = C - U
overlap_removed = len(C) - sum(len(segment) for segment in new_segments)
unique_context_ratio = unique_candidate_characters / considered_candidate_characters
relevant_retention = selected_relevant_chunks / expected_relevant_chunks
```

Exact duplicate text is removed first. Positional subtraction then retains only unseen segments from
overlapping adjacent chunks. The selector enforces 12,000 characters overall and 6,000 per document
by default, including source headings in the total budget. This prevents one document from consuming
all model context while preserving source numbering after selection.

## Generation Scoring Calculations

Natural answers are divided into claims and citations such as `[Source 1]`. Text is Unicode- and
case-normalized; common English/Turkish number words are canonicalized. Stop words are excluded from
the support token set.

An expected fact is present when at least 60% of its content tokens appear in the answer. A cited
claim is supported when at least 60% of its evidence tokens occur in any cited source:

```text
fact_coverage = matched_expected_facts / expected_facts
citation_accuracy = supported_cited_claims / cited_claims
citation_coverage = cited_claims / all_claims
faithfulness = supported_claims / all_claims
hallucination_rate = 1 - faithfulness
refusal_accuracy = correct_refusals / no_result_cases
```

These are deterministic lexical support measures, not a semantic judge. Their value is reproducible
regression detection; their limitation is that valid paraphrases or cross-language answers may be
under-counted. The acceptance record therefore documents observed outputs and does not claim that a
0.688 faithfulness score is a universal measure of truth.

## Performance Calculations and Decision Rule

```text
TTFT = time(first non-empty generated token) - time(request started)
end_to_end = time(stream complete) - time(request started)
tokens_per_second = completion_tokens / generation_seconds
```

Means show typical behavior; P95 exposes slow-tail behavior. A report passes only when every supplied
minimum metric is met, every supplied maximum is not exceeded, and leak counts stay at zero. Optional
features are not promoted merely because they work: their quality improvement must justify measured
latency and inference cost on the same dataset.

## Completion Evidence

- [Phase 4 implementation plan](../../plans/phase-4.md)
- [Retrieval acceptance](../../acceptance/phase-4-retrieval.md)
- [Generation acceptance](../../acceptance/phase-4-generation-baseline.md)
- [Evaluation guide](../../../evaluation/README.md)
- [Retrieval observability](../../api/retrieval-observability.md)

## Lasting Responsibility

The evaluator becomes the promotion gate for later adapters and quantized artifacts. Future phases
must compare against these baselines rather than replacing them with unconnected demonstrations.

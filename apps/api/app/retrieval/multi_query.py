from dataclasses import replace
from time import perf_counter

from sqlalchemy.orm import Session

from app.observability.metrics import metrics_registry
from app.retrieval.contracts import RetrievalCandidate, RetrievalQuery, RetrievalResult, RetrievalStrategy
from app.services.query_rewriters import QueryRewriteError, QueryRewriter


class MultiQueryRetrievalStrategy:
    name = "multi_query"

    def __init__(
        self,
        base: RetrievalStrategy,
        rewriter: QueryRewriter,
        *,
        max_generated_variants: int = 2,
        max_query_chars: int = 500,
        candidates_per_variant: int = 10,
        max_candidate_observations: int = 30,
        max_pipeline_ms: float = 2_000.0,
        rrf_k: int = 60,
    ) -> None:
        self.base = base
        self.rewriter = rewriter
        self.max_generated_variants = max_generated_variants
        self.max_query_chars = max_query_chars
        self.candidates_per_variant = candidates_per_variant
        self.max_candidate_observations = max_candidate_observations
        self.max_pipeline_ms = max_pipeline_ms
        self.rrf_k = rrf_k

    def retrieve(self, db: Session, query: RetrievalQuery) -> RetrievalResult:
        total_started_at = perf_counter()
        rewrite_started_at = perf_counter()
        try:
            generated = self.rewriter.rewrite(
                query.text,
                max_variants=self.max_generated_variants,
            )
            variants = normalize_query_variants(
                query.text,
                generated,
                max_generated=self.max_generated_variants,
                max_chars=self.max_query_chars,
            )
            rewrite_outcome = "success" if len(variants) > 1 else "unchanged"
        except QueryRewriteError:
            variants = [query.text]
            rewrite_outcome = "fallback"
        rewrite_duration_ms = (perf_counter() - rewrite_started_at) * 1000
        metrics_registry.record_operation(
            stage="retrieval",
            operation="query_rewrite",
            outcome=rewrite_outcome,
            duration_ms=rewrite_duration_ms,
            item_count=len(variants) - 1,
        )

        result_sets: list[list[RetrievalCandidate]] = []
        timings_ms: dict[str, float] = {"query_rewrite": round(rewrite_duration_ms, 3)}
        observations = 0
        time_budget_exhausted = False
        for variant_index, variant in enumerate(variants):
            if variant_index and elapsed_ms(total_started_at) >= self.max_pipeline_ms:
                time_budget_exhausted = True
                break
            remaining = self.max_candidate_observations - observations
            if remaining <= 0:
                break
            variant_limit = min(
                max(query.limit, self.candidates_per_variant),
                remaining,
            )
            result = self.base.retrieve(
                db,
                replace(query, text=variant, limit=variant_limit),
            )
            candidates = result.candidates[:remaining]
            result_sets.append(candidates)
            observations += len(candidates)
            timings_ms[f"query_{variant_index}_retrieval"] = round(
                result.timings_ms.get("strategy_total", 0.0),
                3,
            )

        merge_started_at = perf_counter()
        merged = merge_query_results(
            result_sets,
            limit=query.limit,
            rrf_k=self.rrf_k,
        )
        merge_duration_ms = (perf_counter() - merge_started_at) * 1000
        metrics_registry.record_operation(
            stage="retrieval",
            operation="multi_query_merge",
            outcome="success" if merged else "no_result",
            duration_ms=merge_duration_ms,
            item_count=len(merged),
        )
        timings_ms.update(
            {
                "multi_query_merge": round(merge_duration_ms, 3),
                "strategy_total": round(elapsed_ms(total_started_at), 3),
            }
        )
        used_variants = variants[: len(result_sets)]
        return RetrievalResult(
            candidates=merged,
            timings_ms=timings_ms,
            diagnostics={
                "query_rewrite_model": self.rewriter.model,
                "query_rewrite_outcome": rewrite_outcome,
                "query_variant_count": len(used_variants),
                "query_variants": used_variants,
                "query_candidate_observations": observations,
                "query_time_budget_exhausted": time_budget_exhausted,
            },
        )


def normalize_query_variants(
    original: str,
    generated: list[str],
    *,
    max_generated: int,
    max_chars: int,
) -> list[str]:
    variants = [original]
    seen = {original.strip().casefold()}
    for raw_variant in generated:
        variant = " ".join(raw_variant.split())
        key = variant.casefold()
        if not variant or len(variant) > max_chars or key in seen:
            continue
        variants.append(variant)
        seen.add(key)
        if len(variants) - 1 >= max_generated:
            break
    return variants


def merge_query_results(
    result_sets: list[list[RetrievalCandidate]],
    *,
    limit: int,
    rrf_k: int,
) -> list[RetrievalCandidate]:
    candidates_by_chunk: dict[int, RetrievalCandidate] = {}
    ranks_by_chunk: dict[int, dict[str, int]] = {}
    scores_by_chunk: dict[int, dict[str, float]] = {}
    for query_index, candidates in enumerate(result_sets):
        origin = f"query_{query_index}"
        for candidate in candidates:
            candidates_by_chunk.setdefault(candidate.chunk_id, candidate)
            ranks_by_chunk.setdefault(candidate.chunk_id, {})[origin] = candidate.rank
            scores_by_chunk.setdefault(candidate.chunk_id, {})[origin] = candidate.normalized_score

    scored = [
        (
            sum(1.0 / (rrf_k + rank) for rank in ranks.values()),
            ranks.get("query_0", min(ranks.values())),
            chunk_id,
        )
        for chunk_id, ranks in ranks_by_chunk.items()
    ]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    max_score = max((score for score, _, _ in scored), default=1.0)
    return [
        replace(
            candidates_by_chunk[chunk_id],
            raw_score=score,
            normalized_score=score / max_score,
            rank=rank,
            strategy="multi_query",
            strategy_ranks={
                **candidates_by_chunk[chunk_id].strategy_ranks,
                **ranks_by_chunk[chunk_id],
            },
            strategy_scores={
                **candidates_by_chunk[chunk_id].strategy_scores,
                **scores_by_chunk[chunk_id],
            },
        )
        for rank, (score, _, chunk_id) in enumerate(scored[:limit], start=1)
    ]


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000

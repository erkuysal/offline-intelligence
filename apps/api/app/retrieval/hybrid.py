from dataclasses import replace
from time import perf_counter

from sqlalchemy.orm import Session

from app.observability.metrics import metrics_registry
from app.retrieval.contracts import RetrievalCandidate, RetrievalQuery, RetrievalResult
from app.retrieval.dense import DenseRetrievalStrategy
from app.retrieval.lexical import LexicalRetrievalStrategy


class HybridRetrievalStrategy:
    name = "hybrid"

    def __init__(
        self,
        dense: DenseRetrievalStrategy,
        lexical: LexicalRetrievalStrategy,
        *,
        overfetch_multiplier: int = 3,
        max_candidates_per_strategy: int = 100,
        rrf_k: int = 60,
    ) -> None:
        self.dense = dense
        self.lexical = lexical
        self.overfetch_multiplier = overfetch_multiplier
        self.max_candidates_per_strategy = max_candidates_per_strategy
        self.rrf_k = rrf_k

    def retrieve(self, db: Session, query: RetrievalQuery) -> RetrievalResult:
        total_started_at = perf_counter()
        candidate_limit = min(
            query.limit * self.overfetch_multiplier,
            self.max_candidates_per_strategy,
        )
        candidate_query = replace(query, limit=candidate_limit)
        dense_result = self.dense.retrieve(db, candidate_query)
        lexical_result = self.lexical.retrieve(db, candidate_query)

        fusion_started_at = perf_counter()
        candidates = reciprocal_rank_fusion(
            dense_result.candidates,
            lexical_result.candidates,
            limit=query.limit,
            rrf_k=self.rrf_k,
        )
        fusion_duration_ms = (perf_counter() - fusion_started_at) * 1000
        metrics_registry.record_operation(
            stage="retrieval",
            operation="hybrid_fusion",
            outcome="success" if candidates else "no_result",
            duration_ms=fusion_duration_ms,
            item_count=len(candidates),
        )
        return RetrievalResult(
            candidates=candidates,
            timings_ms={
                **{
                    f"dense_{stage}": duration
                    for stage, duration in dense_result.timings_ms.items()
                },
                **{
                    f"lexical_{stage}": duration
                    for stage, duration in lexical_result.timings_ms.items()
                },
                "fusion": round(fusion_duration_ms, 3),
                "strategy_total": round((perf_counter() - total_started_at) * 1000, 3),
            },
        )


def reciprocal_rank_fusion(
    dense_candidates: list[RetrievalCandidate],
    lexical_candidates: list[RetrievalCandidate],
    *,
    limit: int,
    rrf_k: int,
) -> list[RetrievalCandidate]:
    candidates_by_chunk: dict[int, RetrievalCandidate] = {}
    ranks_by_chunk: dict[int, dict[str, int]] = {}
    scores_by_chunk: dict[int, dict[str, float]] = {}

    for strategy, candidates in (
        ("dense", dense_candidates),
        ("lexical", lexical_candidates),
    ):
        for candidate in candidates:
            candidates_by_chunk.setdefault(candidate.chunk_id, candidate)
            ranks_by_chunk.setdefault(candidate.chunk_id, {})[strategy] = candidate.rank
            scores_by_chunk.setdefault(candidate.chunk_id, {})[strategy] = candidate.normalized_score

    scored = [
        (
            sum(1.0 / (rrf_k + rank) for rank in ranks.values()),
            min(ranks.values()),
            chunk_id,
        )
        for chunk_id, ranks in ranks_by_chunk.items()
    ]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    maximum_score = 2.0 / (rrf_k + 1)

    fused: list[RetrievalCandidate] = []
    for fused_rank, (rrf_score, _best_rank, chunk_id) in enumerate(scored[:limit], start=1):
        base = candidates_by_chunk[chunk_id]
        fused.append(
            replace(
                base,
                raw_score=rrf_score,
                normalized_score=rrf_score / maximum_score,
                rank=fused_rank,
                strategy="hybrid",
                strategy_ranks=ranks_by_chunk[chunk_id],
                strategy_scores=scores_by_chunk[chunk_id],
            )
        )
    return fused

from dataclasses import replace
import math
from time import perf_counter

from sqlalchemy.orm import Session

from app.observability.metrics import metrics_registry
from app.retrieval.contracts import RetrievalCandidate, RetrievalQuery, RetrievalResult, RetrievalStrategy
from app.services.rerankers import RerankerError, RerankerProvider


class RerankedRetrievalStrategy:
    name = "reranked"

    def __init__(
        self,
        base: RetrievalStrategy,
        reranker: RerankerProvider,
        *,
        candidate_limit: int = 20,
    ) -> None:
        self.base = base
        self.reranker = reranker
        self.candidate_limit = candidate_limit

    def retrieve(self, db: Session, query: RetrievalQuery) -> RetrievalResult:
        total_started_at = perf_counter()
        candidate_query = replace(query, limit=max(query.limit, self.candidate_limit))
        base_result = self.base.retrieve(db, candidate_query)
        candidates = base_result.candidates[: self.candidate_limit]
        reranker_started_at = perf_counter()
        try:
            scores = self.reranker.score(query.text, [candidate.content for candidate in candidates])
            if len(scores) != len(candidates):
                raise RerankerError("Reranker returned the wrong score count")
            reranked = rerank_candidates(candidates, scores, limit=query.limit)
            outcome = "success"
        except RerankerError:
            reranked = candidates[: query.limit]
            outcome = "fallback"
        reranker_duration_ms = (perf_counter() - reranker_started_at) * 1000
        metrics_registry.record_operation(
            stage="retrieval",
            operation="rerank",
            outcome=outcome,
            duration_ms=reranker_duration_ms,
            item_count=len(candidates),
        )
        return RetrievalResult(
            candidates=reranked,
            timings_ms={
                **base_result.timings_ms,
                "reranker": round(reranker_duration_ms, 3),
                "strategy_total": round((perf_counter() - total_started_at) * 1000, 3),
            },
            diagnostics={
                **base_result.diagnostics,
                "reranker_model": self.reranker.model,
                "reranker_outcome": outcome,
                "reranker_candidate_count": len(candidates),
            },
        )


def rerank_candidates(
    candidates: list[RetrievalCandidate],
    scores: list[float],
    *,
    limit: int,
) -> list[RetrievalCandidate]:
    scored = sorted(
        zip(candidates, scores, strict=True),
        key=lambda item: (-item[1], item[0].rank, item[0].chunk_id),
    )
    return [
        replace(
            candidate,
            raw_score=score,
            normalized_score=normalize_reranker_score(score),
            rank=rank,
            strategy="reranked",
            strategy_ranks={
                **candidate.strategy_ranks,
                "hybrid": candidate.rank,
                "reranker": rank,
            },
            strategy_scores={
                **candidate.strategy_scores,
                "hybrid": candidate.normalized_score,
                "reranker": score,
            },
        )
        for rank, (candidate, score) in enumerate(scored[:limit], start=1)
    ]


def normalize_reranker_score(score: float) -> float:
    if 0.0 <= score <= 1.0:
        return score
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, score))))

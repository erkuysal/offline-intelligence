from app.retrieval import RetrievalCandidate, RetrievalQuery, RetrievalResult
from app.retrieval.reranked import RerankedRetrievalStrategy, rerank_candidates
from app.services.rerankers import RerankerError


def make_candidate(chunk_id: int, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        document_id=chunk_id,
        document_filename=f"document-{chunk_id}.txt",
        chunk_id=chunk_id,
        chunk_index=0,
        content=f"passage {chunk_id}",
        source_page=None,
        source_label=f"passage-{chunk_id}",
        char_start=0,
        char_end=9,
        raw_score=1.0 / rank,
        normalized_score=1.0 / rank,
        rank=rank,
        strategy="hybrid",
        strategy_ranks={"dense": rank, "lexical": rank},
        strategy_scores={"dense": 1.0 / rank, "lexical": 1.0 / rank},
    )


class BaseStrategy:
    name = "hybrid"

    def __init__(self, candidates: list[RetrievalCandidate]) -> None:
        self.candidates = candidates
        self.limits: list[int] = []

    def retrieve(self, _db, query):
        self.limits.append(query.limit)
        return RetrievalResult(self.candidates[: query.limit], {"fusion": 1.0})


class StaticReranker:
    model = "test-reranker"

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def score(self, _query, documents):
        assert len(documents) == len(self.scores)
        return self.scores


class FailedReranker:
    model = "failed-reranker"

    def score(self, _query, _documents):
        raise RerankerError("offline")


def test_reranked_strategy_bounds_pool_and_records_ranks_scores_and_model() -> None:
    base = BaseStrategy([make_candidate(1, 1), make_candidate(2, 2), make_candidate(3, 3)])
    strategy = RerankedRetrievalStrategy(
        base,
        StaticReranker([0.1, 0.9, 0.5]),
        candidate_limit=3,
    )

    result = strategy.retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(text="query", user_id=1, limit=2),
    )

    assert base.limits == [3]
    assert [candidate.chunk_id for candidate in result.candidates] == [2, 3]
    assert result.candidates[0].strategy_ranks["hybrid"] == 2
    assert result.candidates[0].strategy_ranks["reranker"] == 1
    assert result.candidates[0].strategy_scores["reranker"] == 0.9
    assert result.diagnostics == {
        "reranker_model": "test-reranker",
        "reranker_outcome": "success",
        "reranker_candidate_count": 3,
    }
    assert result.timings_ms["reranker"] >= 0


def test_reranked_strategy_falls_back_to_unchanged_fused_order() -> None:
    candidates = [make_candidate(1, 1), make_candidate(2, 2), make_candidate(3, 3)]
    strategy = RerankedRetrievalStrategy(
        BaseStrategy(candidates),
        FailedReranker(),
        candidate_limit=3,
    )

    result = strategy.retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(text="query", user_id=1, limit=2),
    )

    assert result.candidates == candidates[:2]
    assert result.diagnostics["reranker_outcome"] == "fallback"
    assert all(candidate.strategy == "hybrid" for candidate in result.candidates)


def test_rerank_candidates_uses_stable_fused_rank_tie_breaker() -> None:
    reranked = rerank_candidates(
        [make_candidate(9, 1), make_candidate(4, 2)],
        [0.5, 0.5],
        limit=2,
    )

    assert [candidate.chunk_id for candidate in reranked] == [9, 4]

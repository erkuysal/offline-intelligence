from dataclasses import replace

from app.retrieval import (
    HybridRetrievalStrategy,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalResult,
    reciprocal_rank_fusion,
)


def make_candidate(chunk_id: int, rank: int, strategy: str) -> RetrievalCandidate:
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
        strategy=strategy,
        strategy_ranks={strategy: rank},
        strategy_scores={strategy: 1.0 / rank},
    )


def test_rrf_deduplicates_chunks_and_exposes_per_strategy_diagnostics() -> None:
    fused = reciprocal_rank_fusion(
        [make_candidate(1, 1, "dense"), make_candidate(2, 2, "dense")],
        [make_candidate(2, 1, "lexical"), make_candidate(3, 2, "lexical")],
        limit=3,
        rrf_k=60,
    )

    assert [candidate.chunk_id for candidate in fused] == [2, 1, 3]
    assert [candidate.rank for candidate in fused] == [1, 2, 3]
    assert fused[0].strategy == "hybrid"
    assert fused[0].strategy_ranks == {"dense": 2, "lexical": 1}
    assert fused[0].strategy_scores == {"dense": 0.5, "lexical": 1.0}
    assert fused[0].normalized_score <= 1.0


def test_hybrid_overfetches_each_strategy_and_applies_final_limit() -> None:
    class RecordingStrategy:
        def __init__(self, name: str, candidates: list[RetrievalCandidate]) -> None:
            self.name = name
            self.candidates = candidates
            self.limits: list[int] = []

        def retrieve(self, _db, query: RetrievalQuery) -> RetrievalResult:
            self.limits.append(query.limit)
            return RetrievalResult(
                candidates=self.candidates,
                timings_ms={"candidate_retrieval": 1.0},
            )

    dense = RecordingStrategy("dense", [make_candidate(1, 1, "dense")])
    lexical = RecordingStrategy("lexical", [make_candidate(2, 1, "lexical")])
    strategy = HybridRetrievalStrategy(
        dense,  # type: ignore[arg-type]
        lexical,  # type: ignore[arg-type]
        overfetch_multiplier=4,
        max_candidates_per_strategy=10,
        rrf_k=60,
    )

    result = strategy.retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(text="query", user_id=1, limit=2),
    )

    assert dense.limits == [8]
    assert lexical.limits == [8]
    assert len(result.candidates) == 2
    assert result.timings_ms["fusion"] >= 0
    assert "dense_candidate_retrieval" in result.timings_ms
    assert "lexical_candidate_retrieval" in result.timings_ms


def test_rrf_uses_stable_chunk_id_tie_breaker() -> None:
    first = make_candidate(9, 1, "dense")
    second = replace(make_candidate(4, 1, "lexical"), normalized_score=0.2)

    fused = reciprocal_rank_fusion([first], [second], limit=2, rrf_k=60)

    assert [candidate.chunk_id for candidate in fused] == [4, 9]

from app.retrieval import RetrievalCandidate, RetrievalQuery, RetrievalResult
from app.retrieval.multi_query import (
    MultiQueryRetrievalStrategy,
    merge_query_results,
    normalize_query_variants,
)
from app.services.query_rewriters import QueryRewriteError


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
        strategy_ranks={"hybrid": rank},
        strategy_scores={"hybrid": 1.0 / rank},
    )


class StaticRewriter:
    model = "test-rewriter"

    def __init__(self, variants: list[str]) -> None:
        self.variants = variants

    def rewrite(self, _query, *, max_variants):
        return self.variants[:max_variants]


class FailedRewriter:
    model = "failed-rewriter"

    def rewrite(self, _query, *, max_variants):
        raise QueryRewriteError("offline")


class RecordingStrategy:
    name = "hybrid"

    def __init__(self, results_by_query: dict[str, list[RetrievalCandidate]]) -> None:
        self.results_by_query = results_by_query
        self.queries: list[RetrievalQuery] = []

    def retrieve(self, _db, query):
        self.queries.append(query)
        return RetrievalResult(
            self.results_by_query.get(query.text, [])[: query.limit],
            {"strategy_total": 1.0},
        )


def test_multi_query_preserves_filters_bounds_variants_and_deduplicates() -> None:
    base = RecordingStrategy(
        {
            "backup schedule": [make_candidate(1, 1), make_candidate(2, 2)],
            "nightly backups": [make_candidate(2, 1), make_candidate(3, 2)],
        }
    )
    strategy = MultiQueryRetrievalStrategy(
        base,
        StaticRewriter(["  nightly   backups ", "backup schedule", "x" * 501]),
        max_generated_variants=3,
        max_query_chars=500,
        candidates_per_variant=2,
        max_candidate_observations=4,
    )

    result = strategy.retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(
            text="backup schedule",
            user_id=7,
            limit=2,
            document_ids=(11, 12),
        ),
    )

    assert [query.text for query in base.queries] == ["backup schedule", "nightly backups"]
    assert all(query.user_id == 7 and query.document_ids == (11, 12) for query in base.queries)
    assert all(query.limit == 2 for query in base.queries)
    assert [candidate.chunk_id for candidate in result.candidates] == [2, 1]
    assert result.candidates[0].strategy_ranks["query_0"] == 2
    assert result.candidates[0].strategy_ranks["query_1"] == 1
    assert result.diagnostics["query_variant_count"] == 2
    assert result.diagnostics["query_candidate_observations"] == 4


def test_multi_query_falls_back_to_original_query() -> None:
    candidates = [make_candidate(1, 1), make_candidate(2, 2)]
    base = RecordingStrategy({"original": candidates})
    strategy = MultiQueryRetrievalStrategy(base, FailedRewriter(), candidates_per_variant=2)

    result = strategy.retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(text="original", user_id=1, limit=2, document_ids=(9,)),
    )

    assert [query.text for query in base.queries] == ["original"]
    assert [candidate.chunk_id for candidate in result.candidates] == [1, 2]
    assert result.diagnostics["query_rewrite_outcome"] == "fallback"
    assert result.diagnostics["query_variants"] == ["original"]


def test_multi_query_stops_generated_variants_after_time_budget(monkeypatch) -> None:
    base = RecordingStrategy({"original": [make_candidate(1, 1)]})
    strategy = MultiQueryRetrievalStrategy(
        base,
        StaticRewriter(["variant"]),
        max_pipeline_ms=1.0,
    )
    monkeypatch.setattr("app.retrieval.multi_query.elapsed_ms", lambda _started: 2.0)

    result = strategy.retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(text="original", user_id=1, limit=1),
    )

    assert [query.text for query in base.queries] == ["original"]
    assert result.diagnostics["query_time_budget_exhausted"] is True


def test_normalize_query_variants_keeps_original_and_stable_unique_order() -> None:
    assert normalize_query_variants(
        "Original Query",
        [" original query ", "First   variant", "Second", "Third"],
        max_generated=2,
        max_chars=20,
    ) == ["Original Query", "First variant", "Second"]


def test_merge_query_results_uses_stable_chunk_id_tie_breaker() -> None:
    merged = merge_query_results(
        [[make_candidate(9, 1)], [make_candidate(4, 1)]],
        limit=2,
        rrf_k=60,
    )

    assert [candidate.chunk_id for candidate in merged] == [4, 9]
    assert all(candidate.strategy == "multi_query" for candidate in merged)

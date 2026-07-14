from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from app.retrieval import RetrievalCandidate, RetrievalQuery
from app.services.retrieval_runs import (
    build_retrieval_run,
    cleanup_expired_retrieval_runs,
    persist_retrieval_run,
    retrieval_diagnostics_for_persistence,
)


def make_settings(**overrides):
    values = {
        "retrieval_run_persistence_enabled": True,
        "retrieval_run_persist_query_text": False,
        "retrieval_run_persist_passage_text": False,
        "retrieval_run_retention_days": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_candidate() -> RetrievalCandidate:
    return RetrievalCandidate(
        document_id=3,
        document_filename="private-runbook.md",
        chunk_id=8,
        chunk_index=1,
        content="The private recovery phrase is never stored by default.",
        source_page=2,
        source_label="recovery",
        char_start=10,
        char_end=65,
        raw_score=0.1,
        normalized_score=0.9,
        rank=1,
        strategy="dense",
    )


def test_retrieval_run_defaults_exclude_query_and_passage_text() -> None:
    before = datetime.now(UTC)
    candidate = make_candidate()

    run = build_retrieval_run(
        settings=make_settings(),  # type: ignore[arg-type]
        query=RetrievalQuery(text="private recovery phrase", user_id=5, limit=5),
        request_kind="chat",
        strategy="dense",
        model_versions={"embedding": "fake-bow"},
        candidates=[candidate],
        selected_context=[candidate],
        timings_ms={"embedding": 1.23456, "pipeline_total": 2.0},
    )

    assert run.query_text is None
    assert run.query_sha256 != "private recovery phrase"
    assert "content" not in run.candidates[0]
    assert "char_start" not in run.candidates[0]
    assert run.candidate_count == 1
    assert run.selected_context_count == 1
    assert run.timings_ms["embedding"] == 1.235
    assert run.expires_at > before


def test_retrieval_run_can_explicitly_include_diagnostic_text() -> None:
    candidate = make_candidate()

    run = build_retrieval_run(
        settings=make_settings(
            retrieval_run_persist_query_text=True,
            retrieval_run_persist_passage_text=True,
        ),  # type: ignore[arg-type]
        query=RetrievalQuery(text="private recovery phrase", user_id=5, limit=5),
        request_kind="chat",
        strategy="dense",
        model_versions={"embedding": "fake-bow"},
        candidates=[candidate],
        selected_context=[],
        timings_ms={},
    )

    assert run.query_text == "private recovery phrase"
    assert run.candidates[0]["content"] == candidate.content
    assert run.candidates[0]["char_start"] == 10


def test_query_variant_diagnostics_follow_query_text_privacy_policy() -> None:
    diagnostics = {
        "query_rewrite_outcome": "success",
        "query_variants": ["private original", "private rewrite"],
    }

    private = retrieval_diagnostics_for_persistence(
        make_settings(),  # type: ignore[arg-type]
        diagnostics,
    )
    explicit = retrieval_diagnostics_for_persistence(
        make_settings(retrieval_run_persist_query_text=True),  # type: ignore[arg-type]
        diagnostics,
    )

    assert "query_variants" not in private
    assert len(private["query_variant_sha256"]) == 2
    assert "private" not in str(private)
    assert explicit["query_variants"] == ["private original", "private rewrite"]


def test_disabled_retrieval_run_persistence_does_not_touch_session() -> None:
    result = persist_retrieval_run(
        object(),  # type: ignore[arg-type]
        settings=make_settings(retrieval_run_persistence_enabled=False),  # type: ignore[arg-type]
        query=RetrievalQuery(text="question", user_id=5, limit=5),
        request_kind="document_search",
        strategy="dense",
        model_versions={},
        candidates=[],
        selected_context=[],
        timings_ms={},
    )

    assert result is None


def test_retrieval_run_persistence_failure_rolls_back_without_raising() -> None:
    class FailingSession:
        rolled_back = False

        def add(self, _run) -> None:
            raise SQLAlchemyError("diagnostics unavailable")

        def rollback(self) -> None:
            self.rolled_back = True

    session = FailingSession()
    result = persist_retrieval_run(
        session,  # type: ignore[arg-type]
        settings=make_settings(),  # type: ignore[arg-type]
        query=RetrievalQuery(text="question", user_id=5, limit=5),
        request_kind="chat",
        strategy="dense",
        model_versions={},
        candidates=[],
        selected_context=[],
        timings_ms={},
    )

    assert result is None
    assert session.rolled_back is True


def test_cleanup_expired_retrieval_runs_commits_and_returns_deleted_count() -> None:
    class CleanupSession:
        committed = False

        def execute(self, _statement):
            return SimpleNamespace(rowcount=4)

        def commit(self) -> None:
            self.committed = True

    session = CleanupSession()
    deleted = cleanup_expired_retrieval_runs(
        session,  # type: ignore[arg-type]
        now=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert deleted == 4
    assert session.committed is True

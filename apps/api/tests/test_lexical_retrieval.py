from types import SimpleNamespace

from app.retrieval import LexicalRetrievalStrategy, RetrievalQuery
from app.retrieval.lexical import (
    _candidate_from_row,
    normalize_lexical_text,
    prepare_websearch_query,
)


def test_lexical_candidate_preserves_rank_source_and_calibrated_score() -> None:
    chunk = SimpleNamespace(
        id=17,
        document_id=4,
        document=SimpleNamespace(original_filename="runbook.md"),
        chunk_index=2,
        content="Restart service API-503.",
        source_page=3,
        source_label="incident-api-503",
        char_start=100,
        char_end=124,
    )

    candidate = _candidate_from_row(
        chunk,
        raw_score=0.5,
        normalized_score=1 / 3,
        rank=1,
    )

    assert candidate.strategy == "lexical"
    assert candidate.rank == 1
    assert candidate.raw_score == 0.5
    assert candidate.normalized_score == 1 / 3
    assert candidate.source_label == "incident-api-503"


def test_lexical_statement_uses_safe_websearch_and_pre_ranking_filters() -> None:
    class RecordingSession:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return []

    session = RecordingSession()

    result = LexicalRetrievalStrategy().retrieve(
        session,  # type: ignore[arg-type]
        RetrievalQuery(
            text='"API-503" OR yedekleme',
            user_id=42,
            limit=3,
            document_ids=(7, 9),
        ),
    )

    assert result.candidates == []
    sql = str(session.statement)
    assert "websearch_to_tsquery" in sql
    assert "@@" in sql
    assert "documents.owner_id" in sql
    assert "document_permissions.user_id" in sql
    assert "documents.id IN" in sql
    assert sql.index("WHERE") < sql.index("ORDER BY") < sql.index("LIMIT")


def test_lexical_empty_query_returns_without_executing_sql() -> None:
    result = LexicalRetrievalStrategy().retrieve(
        object(),  # type: ignore[arg-type]
        RetrievalQuery(text="   ", user_id=1, limit=5),
    )

    assert result.candidates == []
    assert result.timings_ms["candidate_retrieval"] >= 0


def test_lexical_identifier_normalization_matches_index_expression() -> None:
    assert normalize_lexical_text("API-503 OPS_RUNBOOK:v2.md") == "API 503 OPS RUNBOOK v2 md"


def test_lexical_natural_language_uses_any_term_but_preserves_explicit_syntax() -> None:
    assert prepare_websearch_query("When do backups run?") == "When OR do OR backups OR run?"
    assert prepare_websearch_query('"tam yedek"') == '"tam yedek"'
    assert prepare_websearch_query("backup OR restore") == "backup OR restore"

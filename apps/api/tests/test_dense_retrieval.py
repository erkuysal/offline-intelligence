from types import SimpleNamespace

from app.retrieval import DenseRetrievalStrategy, RetrievalQuery
from app.retrieval.dense import _candidate_from_row
from app.services.embeddings import FakeEmbeddingProvider


def test_dense_candidate_preserves_source_rank_and_public_score() -> None:
    chunk = SimpleNamespace(
        id=17,
        document_id=4,
        document=SimpleNamespace(original_filename="runbook.md"),
        chunk_index=2,
        content="Restore from the latest verified backup.",
        source_page=3,
        source_label="restore-policy",
        char_start=100,
        char_end=140,
    )

    candidate = _candidate_from_row(
        chunk,
        raw_score=0.125,
        normalized_score=0.875,
        rank=1,
    )

    assert candidate.document_id == 4
    assert candidate.document_filename == "runbook.md"
    assert candidate.chunk_id == 17
    assert candidate.rank == 1
    assert candidate.strategy == "dense"
    assert candidate.raw_score == 0.125
    assert candidate.normalized_score == 0.875
    assert candidate.source_label == "restore-policy"


def test_dense_statement_keeps_access_model_and_document_filters_before_ranking() -> None:
    class RecordingSession:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return []

    session = RecordingSession()
    strategy = DenseRetrievalStrategy(FakeEmbeddingProvider(model="fake-bow", dimensions=768))

    result = strategy.retrieve(
        session,  # type: ignore[arg-type]
        RetrievalQuery(
            text="backup policy",
            user_id=42,
            limit=3,
            document_ids=(7, 9),
        ),
    )

    assert result.candidates == []
    sql = str(session.statement)
    assert "documents.owner_id" in sql
    assert "document_permissions.user_id" in sql
    assert "document_permissions.permission" in sql
    assert "document_chunks.embedding_model" in sql
    assert "documents.id IN" in sql
    assert sql.index("WHERE") < sql.index("ORDER BY") < sql.index("LIMIT")

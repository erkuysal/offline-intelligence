from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine
from app.models.document import Document, DocumentChunk, DocumentPermission
from app.models.user import User
from app.retrieval import (
    DenseRetrievalStrategy,
    HybridRetrievalStrategy,
    LexicalRetrievalStrategy,
    RetrievalQuery,
)
from app.services.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.usefixtures("clean_database")


def test_dense_strategy_enforces_access_filters_before_ranking_in_one_query() -> None:
    provider = FakeEmbeddingProvider(model="fake-bow", dimensions=768)
    with SessionLocal() as db:
        owner = create_user(db, "owner@example.com")
        reader = create_user(db, "reader@example.com")
        outsider = create_user(db, "outsider@example.com")
        private = create_document(db, owner.id, "private.txt", "secret launch alpha", provider)
        shared = create_document(db, owner.id, "shared.txt", "shared backup plan", provider)
        db.add(
            DocumentPermission(
                document_id=shared.id,
                user_id=reader.id,
                permission="read",
            )
        )
        db.commit()

        strategy = DenseRetrievalStrategy(provider)
        with count_select_queries() as owner_query_count:
            owner_result = strategy.retrieve(
                db,
                RetrievalQuery(
                    text="secret launch alpha shared backup",
                    user_id=owner.id,
                    limit=5,
                ),
            )

        assert owner_query_count == [1]
        assert {candidate.document_id for candidate in owner_result.candidates} == {
            private.id,
            shared.id,
        }

        reader_result = strategy.retrieve(
            db,
            RetrievalQuery(
                text="secret launch alpha shared backup",
                user_id=reader.id,
                limit=5,
            ),
        )
        assert [candidate.document_id for candidate in reader_result.candidates] == [shared.id]

        outsider_result = strategy.retrieve(
            db,
            RetrievalQuery(
                text="secret launch alpha shared backup",
                user_id=outsider.id,
                limit=5,
            ),
        )
        assert outsider_result.candidates == []

        filtered_result = strategy.retrieve(
            db,
            RetrievalQuery(
                text="secret launch alpha",
                user_id=owner.id,
                limit=1,
                document_ids=(shared.id,),
            ),
        )
        assert [candidate.document_id for candidate in filtered_result.candidates] == [shared.id]

def test_lexical_strategy_covers_terms_filenames_phrases_and_access_in_one_query() -> None:
    provider = FakeEmbeddingProvider(model="fake-bow", dimensions=768)
    with SessionLocal() as db:
        owner = create_user(db, "lexical-owner@example.com")
        reader = create_user(db, "lexical-reader@example.com")
        outsider = create_user(db, "lexical-outsider@example.com")
        private = create_document(
            db,
            owner.id,
            "incident-ZX-991.txt",
            "The private incident requires a cold restart.",
            provider,
        )
        shared = create_document(
            db,
            owner.id,
            "shared-runbook.txt",
            "OPS-442 için tam yedek her pazar gecesi alınır.",
            provider,
        )
        db.add(
            DocumentPermission(
                document_id=shared.id,
                user_id=reader.id,
                permission="read",
            )
        )
        db.commit()

        strategy = LexicalRetrievalStrategy()
        with count_select_queries() as owner_query_count:
            filename_result = strategy.retrieve(
                db,
                RetrievalQuery(text="ZX-991", user_id=owner.id, limit=5),
            )
        assert owner_query_count == [1]
        assert [candidate.document_id for candidate in filename_result.candidates] == [private.id]

        phrase_result = strategy.retrieve(
            db,
            RetrievalQuery(text='"tam yedek"', user_id=reader.id, limit=5),
        )
        assert [candidate.document_id for candidate in phrase_result.candidates] == [shared.id]

        private_reader_result = strategy.retrieve(
            db,
            RetrievalQuery(text="ZX-991", user_id=reader.id, limit=5),
        )
        assert private_reader_result.candidates == []

        outsider_result = strategy.retrieve(
            db,
            RetrievalQuery(text="OPS-442", user_id=outsider.id, limit=5),
        )
        assert outsider_result.candidates == []

        filtered_result = strategy.retrieve(
            db,
            RetrievalQuery(
                text="ZX-991 OR OPS-442",
                user_id=owner.id,
                limit=1,
                document_ids=(shared.id,),
            ),
        )
        assert [candidate.document_id for candidate in filtered_result.candidates] == [shared.id]

        for edge_query in ("---", '"unterminated phrase', "the and or"):
            edge_result = strategy.retrieve(
                db,
                RetrievalQuery(text=edge_query, user_id=owner.id, limit=5),
            )
            assert isinstance(edge_result.candidates, list)


def test_hybrid_strategy_fuses_without_duplicates_and_preserves_access_filters() -> None:
    provider = FakeEmbeddingProvider(model="fake-bow", dimensions=768)
    with SessionLocal() as db:
        owner = create_user(db, "hybrid-owner@example.com")
        reader = create_user(db, "hybrid-reader@example.com")
        outsider = create_user(db, "hybrid-outsider@example.com")
        private = create_document(
            db,
            owner.id,
            "private-restore.txt",
            "A recovery rehearsal is scheduled every Friday.",
            provider,
        )
        shared = create_document(
            db,
            owner.id,
            "shared-backup.txt",
            "OPS-442 backups run nightly.",
            provider,
        )
        db.add(
            DocumentPermission(
                document_id=shared.id,
                user_id=reader.id,
                permission="read",
            )
        )
        db.commit()

        strategy = HybridRetrievalStrategy(
            DenseRetrievalStrategy(provider),
            LexicalRetrievalStrategy(),
            overfetch_multiplier=3,
            max_candidates_per_strategy=20,
            rrf_k=60,
        )
        with count_select_queries() as owner_query_count:
            owner_result = strategy.retrieve(
                db,
                RetrievalQuery(text="Friday recovery rehearsal", user_id=owner.id, limit=5),
            )
        assert owner_query_count == [2]
        assert owner_result.candidates[0].document_id == private.id
        assert len({candidate.chunk_id for candidate in owner_result.candidates}) == len(
            owner_result.candidates
        )
        assert owner_result.candidates[0].strategy == "hybrid"
        assert set(owner_result.candidates[0].strategy_ranks) == {"dense", "lexical"}

        reader_result = strategy.retrieve(
            db,
            RetrievalQuery(text="OPS-442 backups", user_id=reader.id, limit=5),
        )
        assert {candidate.document_id for candidate in reader_result.candidates} == {shared.id}

        outsider_result = strategy.retrieve(
            db,
            RetrievalQuery(text="OPS-442 backups", user_id=outsider.id, limit=5),
        )
        assert outsider_result.candidates == []

        filtered_result = strategy.retrieve(
            db,
            RetrievalQuery(
                text="Friday recovery OPS-442",
                user_id=owner.id,
                limit=1,
                document_ids=(shared.id,),
            ),
        )
        assert [candidate.document_id for candidate in filtered_result.candidates] == [shared.id]


def create_user(db: Session, email: str) -> User:
    user = User(email=email, password_hash="test-password-hash")
    db.add(user)
    db.flush()
    return user


def create_document(
    db: Session,
    owner_id: int,
    filename: str,
    content: str,
    provider: FakeEmbeddingProvider,
) -> Document:
    document = Document(
        owner_id=owner_id,
        original_filename=filename,
        content_type="text/plain",
        size_bytes=len(content),
        storage_path=f"tests/{owner_id}/{filename}",
        checksum_sha256=(filename.encode().hex() + "0" * 64)[:64],
        chunk_count=1,
        status="ready",
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content=content,
            char_start=0,
            char_end=len(content),
            token_start=0,
            token_end=len(content.split()),
            source_label=filename,
            embedding=provider.embed_texts([content])[0],
            embedding_model=provider.model,
        )
    )
    db.flush()
    return document


@contextmanager
def count_select_queries() -> Iterator[list[int]]:
    counts = [0]

    def before_cursor_execute(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            counts[0] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

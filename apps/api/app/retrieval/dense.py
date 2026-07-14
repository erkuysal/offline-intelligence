from time import perf_counter

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.constants import EMBEDDING_DIMENSIONS
from app.models.document import Document, DocumentChunk, DocumentPermission
from app.observability.metrics import metrics_registry
from app.retrieval.contracts import RetrievalCandidate, RetrievalQuery, RetrievalResult
from app.services.embeddings import EmbeddingProvider, validate_embeddings


class DenseRetrievalStrategy:
    name = "dense"

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    def retrieve(self, db: Session, query: RetrievalQuery) -> RetrievalResult:
        total_started_at = perf_counter()
        embedding_started_at = perf_counter()
        try:
            query_embeddings = self.provider.embed_texts([query.text])
            validate_embeddings(
                query_embeddings,
                expected_count=1,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        except Exception:
            _record_embedding_metric("failure", embedding_started_at)
            raise
        embedding_duration_ms = (perf_counter() - embedding_started_at) * 1000
        _record_embedding_metric("success", embedding_started_at)

        distance = DocumentChunk.embedding.cosine_distance(query_embeddings[0])
        statement = (
            select(
                DocumentChunk,
                distance.label("raw_score"),
                (1 - distance).label("normalized_score"),
            )
            .join(Document)
            .options(contains_eager(DocumentChunk.document))
            .where(
                Document.status == "ready",
                or_(
                    Document.owner_id == query.user_id,
                    exists().where(
                        DocumentPermission.document_id == Document.id,
                        DocumentPermission.user_id == query.user_id,
                        DocumentPermission.permission == "read",
                    ),
                ),
                DocumentChunk.embedding.is_not(None),
                DocumentChunk.embedding_model == self.provider.model,
            )
            .order_by(distance)
            .limit(query.limit)
        )
        if query.document_ids is not None:
            statement = statement.where(Document.id.in_(query.document_ids))

        retrieval_started_at = perf_counter()
        try:
            rows = list(db.execute(statement))
        except Exception:
            _record_retrieval_metric("failure", retrieval_started_at)
            raise

        candidates = [
            _candidate_from_row(
                chunk,
                raw_score=float(raw_score),
                normalized_score=float(normalized_score),
                rank=rank,
            )
            for rank, (chunk, raw_score, normalized_score) in enumerate(rows, start=1)
        ]
        _record_retrieval_metric(
            "success" if candidates else "no_result",
            retrieval_started_at,
            item_count=len(candidates),
        )
        retrieval_duration_ms = (perf_counter() - retrieval_started_at) * 1000
        return RetrievalResult(
            candidates=candidates,
            timings_ms={
                "embedding": round(embedding_duration_ms, 3),
                "candidate_retrieval": round(retrieval_duration_ms, 3),
                "strategy_total": round((perf_counter() - total_started_at) * 1000, 3),
            },
        )


def _candidate_from_row(
    chunk: DocumentChunk,
    raw_score: float,
    normalized_score: float,
    rank: int,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        document_id=chunk.document_id,
        document_filename=chunk.document.original_filename,
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        source_page=chunk.source_page,
        source_label=chunk.source_label,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        raw_score=raw_score,
        # Cosine similarity is the existing public score. Cross-strategy
        # calibration beyond this transformation is deferred until hybrid retrieval.
        normalized_score=normalized_score,
        rank=rank,
        strategy=DenseRetrievalStrategy.name,
        strategy_ranks={DenseRetrievalStrategy.name: rank},
        strategy_scores={DenseRetrievalStrategy.name: normalized_score},
    )


def _record_embedding_metric(outcome: str, started_at: float) -> None:
    metrics_registry.record_operation(
        stage="embedding",
        operation="query",
        outcome=outcome,
        duration_ms=(perf_counter() - started_at) * 1000,
        item_count=1 if outcome == "success" else 0,
    )


def _record_retrieval_metric(
    outcome: str,
    started_at: float,
    *,
    item_count: int = 0,
) -> None:
    metrics_registry.record_operation(
        stage="retrieval",
        operation="dense_search",
        outcome=outcome,
        duration_ms=(perf_counter() - started_at) * 1000,
        item_count=item_count,
    )

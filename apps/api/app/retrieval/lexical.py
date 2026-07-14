from time import perf_counter

from sqlalchemy import exists, func, literal_column, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.models.document import Document, DocumentChunk, DocumentPermission
from app.observability.metrics import metrics_registry
from app.retrieval.contracts import RetrievalCandidate, RetrievalQuery, RetrievalResult


class LexicalRetrievalStrategy:
    name = "lexical"
    text_search_config = "simple"

    def retrieve(self, db: Session, query: RetrievalQuery) -> RetrievalResult:
        total_started_at = perf_counter()
        websearch_query = prepare_websearch_query(query.text)
        if not websearch_query:
            duration_ms = _record_retrieval_metric("no_result", total_started_at)
            return RetrievalResult(
                candidates=[],
                timings_ms={
                    "candidate_retrieval": round(duration_ms, 3),
                    "strategy_total": round(duration_ms, 3),
                },
            )

        tsquery = func.websearch_to_tsquery(
            literal_column("'simple'::regconfig"),
            websearch_query,
        )
        content_rank = func.ts_rank_cd(DocumentChunk.search_vector, tsquery)
        filename_rank = func.ts_rank_cd(Document.search_vector, tsquery)
        rank_score = func.greatest(content_rank, filename_rank)
        normalized_score = rank_score / (1.0 + rank_score)
        statement = (
            select(
                DocumentChunk,
                rank_score.label("raw_score"),
                normalized_score.label("normalized_score"),
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
                or_(
                    DocumentChunk.search_vector.op("@@")(tsquery),
                    Document.search_vector.op("@@")(tsquery),
                ),
            )
            .order_by(rank_score.desc(), DocumentChunk.id.asc())
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
                normalized_score=float(candidate_score),
                rank=rank,
            )
            for rank, (chunk, raw_score, candidate_score) in enumerate(rows, start=1)
        ]
        retrieval_duration_ms = _record_retrieval_metric(
            "success" if candidates else "no_result",
            retrieval_started_at,
            item_count=len(candidates),
        )
        return RetrievalResult(
            candidates=candidates,
            timings_ms={
                "candidate_retrieval": round(retrieval_duration_ms, 3),
                "strategy_total": round((perf_counter() - total_started_at) * 1000, 3),
            },
        )


def normalize_lexical_text(text: str) -> str:
    return " ".join(text.translate(str.maketrans("-_./:", "     ")).split())


def prepare_websearch_query(text: str) -> str:
    normalized = normalize_lexical_text(text)
    if not normalized:
        return ""
    if '"' in normalized or any(
        token.upper() in {"OR", "AND", "NOT"} for token in normalized.split()
    ):
        return normalized
    return " OR ".join(normalized.split())


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
        normalized_score=normalized_score,
        rank=rank,
        strategy=LexicalRetrievalStrategy.name,
        strategy_ranks={LexicalRetrievalStrategy.name: rank},
        strategy_scores={LexicalRetrievalStrategy.name: normalized_score},
    )


def _record_retrieval_metric(
    outcome: str,
    started_at: float,
    *,
    item_count: int = 0,
) -> float:
    duration_ms = (perf_counter() - started_at) * 1000
    metrics_registry.record_operation(
        stage="retrieval",
        operation="lexical_search",
        outcome=outcome,
        duration_ms=duration_ms,
        item_count=item_count,
    )
    return duration_ms

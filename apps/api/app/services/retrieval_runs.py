from datetime import UTC, datetime, timedelta
import hashlib
from time import perf_counter
from typing import Mapping

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.retrieval import RetrievalRun
from app.observability.metrics import metrics_registry
from app.retrieval import RetrievalCandidate, RetrievalQuery


def persist_retrieval_run(
    db: Session,
    *,
    settings: Settings,
    query: RetrievalQuery,
    request_kind: str,
    strategy: str,
    model_versions: dict[str, object],
    candidates: list[RetrievalCandidate],
    selected_context: list[RetrievalCandidate],
    timings_ms: dict[str, float],
    selection_metrics: Mapping[str, object] | None = None,
    outcome: str | None = None,
) -> RetrievalRun | None:
    if not settings.retrieval_run_persistence_enabled:
        return None

    run = build_retrieval_run(
        settings=settings,
        query=query,
        request_kind=request_kind,
        strategy=strategy,
        model_versions=model_versions,
        candidates=candidates,
        selected_context=selected_context,
        timings_ms=timings_ms,
        selection_metrics=selection_metrics,
        outcome=outcome,
    )
    started_at = perf_counter()
    try:
        db.add(run)
        db.commit()
        db.refresh(run)
    except SQLAlchemyError:
        db.rollback()
        _record_persistence_metric("failure", started_at)
        return None
    _record_persistence_metric("success", started_at)
    return run


def build_retrieval_run(
    *,
    settings: Settings,
    query: RetrievalQuery,
    request_kind: str,
    strategy: str,
    model_versions: dict[str, object],
    candidates: list[RetrievalCandidate],
    selected_context: list[RetrievalCandidate],
    timings_ms: dict[str, float],
    selection_metrics: Mapping[str, object] | None = None,
    outcome: str | None = None,
) -> RetrievalRun:
    now = datetime.now(UTC)
    return RetrievalRun(
        owner_id=query.user_id,
        request_kind=request_kind,
        strategy=strategy,
        outcome=outcome or ("success" if candidates else "no_result"),
        query_sha256=hashlib.sha256(query.text.encode("utf-8")).hexdigest(),
        query_text=query.text if settings.retrieval_run_persist_query_text else None,
        filters={
            "document_ids": list(query.document_ids) if query.document_ids is not None else None,
            "limit": query.limit,
        },
        model_versions=model_versions,
        candidates=[
            serialize_candidate(
                candidate,
                include_passage_text=settings.retrieval_run_persist_passage_text,
            )
            for candidate in candidates
        ],
        selected_context=[
            serialize_candidate(
                candidate,
                include_passage_text=settings.retrieval_run_persist_passage_text,
            )
            for candidate in selected_context
        ],
        timings_ms={key: round(value, 3) for key, value in timings_ms.items()},
        selection_metrics=dict(selection_metrics or {}),
        candidate_count=len(candidates),
        selected_context_count=len(selected_context),
        expires_at=now + timedelta(days=settings.retrieval_run_retention_days),
    )


def serialize_candidate(
    candidate: RetrievalCandidate,
    *,
    include_passage_text: bool,
) -> dict[str, object]:
    diagnostic: dict[str, object] = {
        "document_id": candidate.document_id,
        "document_filename": candidate.document_filename,
        "chunk_id": candidate.chunk_id,
        "chunk_index": candidate.chunk_index,
        "source_page": candidate.source_page,
        "source_label": candidate.source_label,
        "raw_score": candidate.raw_score,
        "normalized_score": candidate.normalized_score,
        "rank": candidate.rank,
        "strategy": candidate.strategy,
        "strategy_ranks": candidate.strategy_ranks,
        "strategy_scores": candidate.strategy_scores,
    }
    if include_passage_text:
        diagnostic["content"] = candidate.content
        diagnostic["char_start"] = candidate.char_start
        diagnostic["char_end"] = candidate.char_end
    return diagnostic


def cleanup_expired_retrieval_runs(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = now or datetime.now(UTC)
    result = db.execute(delete(RetrievalRun).where(RetrievalRun.expires_at <= cutoff))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def record_retrieval_stage(
    *,
    operation: str,
    outcome: str,
    started_at: float,
    item_count: int = 0,
) -> float:
    duration_ms = (perf_counter() - started_at) * 1000
    metrics_registry.record_operation(
        stage="retrieval",
        operation=operation,
        outcome=outcome,
        duration_ms=duration_ms,
        item_count=item_count,
    )
    return duration_ms


def record_retrieval_observation(
    *,
    operation: str,
    outcome: str,
    duration_ms: float,
    item_count: int,
) -> None:
    metrics_registry.record_operation(
        stage="retrieval",
        operation=operation,
        outcome=outcome,
        duration_ms=duration_ms,
        item_count=item_count,
    )


def _record_persistence_metric(outcome: str, started_at: float) -> None:
    metrics_registry.record_operation(
        stage="retrieval",
        operation="persist_run",
        outcome=outcome,
        duration_ms=(perf_counter() - started_at) * 1000,
        item_count=1 if outcome == "success" else 0,
    )

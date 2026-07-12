from dataclasses import dataclass
import json

from redis import Redis
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import SessionLocal
from app.observability.metrics import metrics_registry
from app.services.document_ingestion import process_document_ingestion


@dataclass(frozen=True)
class DocumentIngestionJob:
    document_id: int
    attempt: int = 1
    payload: str = ""

    def encode(self) -> str:
        return json.dumps(
            {"document_id": self.document_id, "attempt": self.attempt},
            separators=(",", ":"),
            sort_keys=True,
        )


def enqueue_document_ingestion(
    redis_client: Redis,
    *,
    queue_name: str,
    document_id: int,
    attempt: int = 1,
) -> None:
    redis_client.rpush(queue_name, DocumentIngestionJob(document_id, attempt).encode())


def reserve_document_ingestion(
    redis_client: Redis,
    *,
    queue_name: str,
    timeout_seconds: int,
) -> DocumentIngestionJob | None:
    payload = redis_client.brpoplpush(
        queue_name,
        processing_queue_name(queue_name),
        timeout=timeout_seconds,
    )
    if payload is None:
        return None
    normalized_payload = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    try:
        return decode_job(normalized_payload)
    except ValueError:
        acknowledge_document_ingestion(
            redis_client,
            queue_name=queue_name,
            payload=normalized_payload,
        )
        return None


def acknowledge_document_ingestion(redis_client: Redis, *, queue_name: str, payload: str) -> None:
    redis_client.lrem(processing_queue_name(queue_name), 1, payload)


def recover_reserved_ingestion_jobs(redis_client: Redis, *, queue_name: str) -> int:
    recovered = 0
    processing_queue = processing_queue_name(queue_name)
    while redis_client.rpoplpush(processing_queue, queue_name) is not None:
        recovered += 1
    return recovered


def processing_queue_name(queue_name: str) -> str:
    return f"{queue_name}:processing"


def decode_job(payload: str) -> DocumentIngestionJob:
    try:
        raw_job = json.loads(payload)
    except json.JSONDecodeError:
        raw_job = None

    if isinstance(raw_job, dict):
        document_id = raw_job.get("document_id")
        attempt = raw_job.get("attempt", 1)
        if isinstance(document_id, int) and isinstance(attempt, int) and attempt >= 1:
            return DocumentIngestionJob(document_id=document_id, attempt=attempt, payload=payload)

    if payload.isdigit():
        return DocumentIngestionJob(document_id=int(payload), payload=payload)
    raise ValueError("Invalid document ingestion job payload")


def mark_document_ingestion_failed(db: Session, document_id: int, attempts: int) -> None:
    from app.models.document import Document

    document = db.get(Document, document_id)
    if document is None:
        return
    document.status = "failed"
    document.ingestion_error = f"Ingestion failed after {attempts} attempts"
    document.chunk_count = 0
    db.commit()


def process_next_ingestion_job(redis_client: Redis, *, settings: Settings) -> bool:
    job = reserve_document_ingestion(
        redis_client,
        queue_name=settings.document_ingestion_queue_name,
        timeout_seconds=settings.document_ingestion_worker_poll_seconds,
    )
    if job is None:
        return False

    try:
        with SessionLocal() as db:
            process_document_ingestion(db, job.document_id, settings=settings)
    except Exception:
        if job.attempt < settings.document_ingestion_max_attempts:
            enqueue_document_ingestion(
                redis_client,
                queue_name=settings.document_ingestion_queue_name,
                document_id=job.document_id,
                attempt=job.attempt + 1,
            )
            metrics_registry.record_operation(
                stage="ingestion",
                operation="queue_delivery",
                outcome="retry",
                duration_ms=0,
                item_count=1,
            )
        else:
            with SessionLocal() as db:
                mark_document_ingestion_failed(db, job.document_id, job.attempt)
            metrics_registry.record_operation(
                stage="ingestion",
                operation="queue_delivery",
                outcome="failed",
                duration_ms=0,
                item_count=1,
            )
    acknowledge_document_ingestion(
        redis_client,
        queue_name=settings.document_ingestion_queue_name,
        payload=job.payload,
    )
    return True

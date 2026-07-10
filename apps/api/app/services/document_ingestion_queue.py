from dataclasses import dataclass

from redis import Redis

from app.config import Settings
from app.db.session import SessionLocal
from app.services.document_ingestion import process_document_ingestion


@dataclass(frozen=True)
class DocumentIngestionJob:
    document_id: int


def enqueue_document_ingestion(
    redis_client: Redis,
    *,
    queue_name: str,
    document_id: int,
) -> None:
    redis_client.rpush(queue_name, str(document_id))


def dequeue_document_ingestion(
    redis_client: Redis,
    *,
    queue_name: str,
    timeout_seconds: int,
) -> DocumentIngestionJob | None:
    item = redis_client.blpop([queue_name], timeout=timeout_seconds)
    if item is None:
        return None

    _, raw_document_id = item
    return DocumentIngestionJob(document_id=int(raw_document_id))


def process_next_ingestion_job(redis_client: Redis, *, settings: Settings) -> bool:
    job = dequeue_document_ingestion(
        redis_client,
        queue_name=settings.document_ingestion_queue_name,
        timeout_seconds=settings.document_ingestion_worker_poll_seconds,
    )
    if job is None:
        return False

    with SessionLocal() as db:
        process_document_ingestion(db, job.document_id, settings=settings)
    return True

from collections.abc import Iterator
from contextlib import contextmanager

from app.config import get_settings
from app.services.document_ingestion_queue import (
    acknowledge_document_ingestion,
    enqueue_document_ingestion,
    process_next_ingestion_job,
    processing_queue_name,
    recover_reserved_ingestion_jobs,
    reserve_document_ingestion,
)


class FakeRedis:
    def __init__(self) -> None:
        self.queues: dict[str, list[str]] = {}

    def rpush(self, queue_name: str, value: str) -> None:
        self.queues.setdefault(queue_name, []).append(value)

    def brpoplpush(self, source: str, destination: str, timeout: int) -> str | None:
        assert timeout == 1
        source_items = self.queues.setdefault(source, [])
        if not source_items:
            return None
        value = source_items.pop()
        self.queues.setdefault(destination, []).insert(0, value)
        return value

    def rpoplpush(self, source: str, destination: str) -> str | None:
        source_items = self.queues.setdefault(source, [])
        if not source_items:
            return None
        value = source_items.pop()
        self.queues.setdefault(destination, []).insert(0, value)
        return value

    def lrem(self, queue_name: str, count: int, value: str) -> int:
        assert count == 1
        items = self.queues.setdefault(queue_name, [])
        try:
            items.remove(value)
        except ValueError:
            return 0
        return 1


def test_document_ingestion_queue_reserves_and_acknowledges_job() -> None:
    redis_client = FakeRedis()

    enqueue_document_ingestion(redis_client, queue_name="documents", document_id=42)  # type: ignore[arg-type]
    job = reserve_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]

    assert job is not None
    assert job.document_id == 42
    assert job.attempt == 1
    assert redis_client.queues[processing_queue_name("documents")] == [job.payload]

    acknowledge_document_ingestion(  # type: ignore[arg-type]
        redis_client,
        queue_name="documents",
        payload=job.payload,
    )
    assert redis_client.queues[processing_queue_name("documents")] == []


def test_document_ingestion_queue_returns_none_when_empty() -> None:
    redis_client = FakeRedis()

    job = reserve_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]

    assert job is None


def test_document_ingestion_queue_discards_malformed_payload() -> None:
    redis_client = FakeRedis()
    redis_client.rpush("documents", "not-a-job")

    job = reserve_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]

    assert job is None
    assert redis_client.queues[processing_queue_name("documents")] == []


def test_document_ingestion_queue_recovers_interrupted_jobs() -> None:
    redis_client = FakeRedis()
    enqueue_document_ingestion(redis_client, queue_name="documents", document_id=42)  # type: ignore[arg-type]
    job = reserve_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]
    assert job is not None

    recovered = recover_reserved_ingestion_jobs(redis_client, queue_name="documents")  # type: ignore[arg-type]

    assert recovered == 1
    assert redis_client.queues[processing_queue_name("documents")] == []
    recovered_job = reserve_document_ingestion(  # type: ignore[arg-type]
        redis_client,
        queue_name="documents",
        timeout_seconds=1,
    )
    assert recovered_job == job


def test_failed_ingestion_is_requeued_with_incremented_attempt(monkeypatch) -> None:
    redis_client = FakeRedis()
    settings = get_settings()
    monkeypatch.setattr(settings, "document_ingestion_queue_name", "documents")
    monkeypatch.setattr(settings, "document_ingestion_worker_poll_seconds", 1)
    monkeypatch.setattr(settings, "document_ingestion_max_attempts", 3)
    enqueue_document_ingestion(redis_client, queue_name="documents", document_id=42)  # type: ignore[arg-type]
    monkeypatch.setattr("app.services.document_ingestion_queue.SessionLocal", fake_session)
    monkeypatch.setattr(
        "app.services.document_ingestion_queue.process_document_ingestion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("temporary failure")),
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        "app.services.document_ingestion_queue.metrics_registry.record_operation",
        lambda **kwargs: recorded.append(kwargs),
    )

    assert process_next_ingestion_job(redis_client, settings=settings) is True  # type: ignore[arg-type]

    retry = reserve_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]
    assert retry is not None
    assert retry.document_id == 42
    assert retry.attempt == 2
    assert recorded == [
        {
            "stage": "ingestion",
            "operation": "queue_delivery",
            "outcome": "retry",
            "duration_ms": 0,
            "item_count": 1,
        }
    ]


def test_final_failed_ingestion_is_not_requeued(monkeypatch) -> None:
    redis_client = FakeRedis()
    settings = get_settings()
    monkeypatch.setattr(settings, "document_ingestion_queue_name", "documents")
    monkeypatch.setattr(settings, "document_ingestion_worker_poll_seconds", 1)
    monkeypatch.setattr(settings, "document_ingestion_max_attempts", 3)
    enqueue_document_ingestion(redis_client, queue_name="documents", document_id=42, attempt=3)  # type: ignore[arg-type]
    monkeypatch.setattr("app.services.document_ingestion_queue.SessionLocal", fake_session)
    monkeypatch.setattr(
        "app.services.document_ingestion_queue.process_document_ingestion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("permanent failure")),
    )
    failed: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.document_ingestion_queue.mark_document_ingestion_failed",
        lambda db, document_id, attempts: failed.append((document_id, attempts)),
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        "app.services.document_ingestion_queue.metrics_registry.record_operation",
        lambda **kwargs: recorded.append(kwargs),
    )

    assert process_next_ingestion_job(redis_client, settings=settings) is True  # type: ignore[arg-type]

    assert failed == [(42, 3)]
    assert redis_client.queues["documents"] == []
    assert redis_client.queues[processing_queue_name("documents")] == []
    assert recorded == [
        {
            "stage": "ingestion",
            "operation": "queue_delivery",
            "outcome": "failed",
            "duration_ms": 0,
            "item_count": 1,
        }
    ]


@contextmanager
def fake_session() -> Iterator[object]:
    yield object()

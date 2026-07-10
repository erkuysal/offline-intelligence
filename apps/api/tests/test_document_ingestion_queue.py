from app.services.document_ingestion_queue import (
    dequeue_document_ingestion,
    enqueue_document_ingestion,
)


class FakeRedis:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def rpush(self, queue_name: str, value: str) -> None:
        self.items.append((queue_name, value))

    def blpop(self, queue_names: list[str], timeout: int) -> tuple[str, str] | None:
        assert timeout == 1
        for index, item in enumerate(self.items):
            if item[0] in queue_names:
                return self.items.pop(index)
        return None


def test_document_ingestion_queue_round_trip() -> None:
    redis_client = FakeRedis()

    enqueue_document_ingestion(redis_client, queue_name="documents", document_id=42)  # type: ignore[arg-type]
    job = dequeue_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]

    assert job is not None
    assert job.document_id == 42


def test_document_ingestion_queue_returns_none_when_empty() -> None:
    redis_client = FakeRedis()

    job = dequeue_document_ingestion(redis_client, queue_name="documents", timeout_seconds=1)  # type: ignore[arg-type]

    assert job is None

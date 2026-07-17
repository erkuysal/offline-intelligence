from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.config import get_settings
from app.main import app
from app.services.embeddings import EmbeddingError

client = TestClient(app)


def test_embedding_health_exposes_safe_runtime_metadata() -> None:
    response = client.get("/health/embedding")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "embedding"
    assert body["status"] == "healthy"
    assert body["metadata"] == {
        "backend": get_settings().embedding_backend,
        "model": get_settings().embedding_model,
        "dimensions": get_settings().embedding_dimensions,
    }


def test_embedding_health_returns_actionable_safe_failure(monkeypatch) -> None:
    class FailedProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("secret upstream response")

    monkeypatch.setattr("app.main.get_embedding_provider", lambda: FailedProvider())

    response = client.get("/health/embedding")

    assert response.status_code == 503
    assert response.json()["code"] == "embedding_unavailable"
    assert response.json()["detail"] == "Embedding backend health check failed"
    assert "secret upstream response" not in response.text


def test_worker_health_reports_synchronous_ingestion(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "document_ingestion_mode", "sync")

    response = client.get("/health/worker")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["metadata"]["mode"] == "sync"


def test_worker_health_reports_queue_without_claiming_worker_liveness(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "document_ingestion_mode", "redis")
    monkeypatch.setattr("app.main.ping_redis", lambda: True)

    response = client.get("/health/worker")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["code"] == "worker_heartbeat_unavailable"


def test_worker_health_reports_queue_failure(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "document_ingestion_mode", "redis")

    def fail() -> None:
        raise RedisError("redis://user:password@private-host")

    monkeypatch.setattr("app.main.ping_redis", fail)

    response = client.get("/health/worker")

    assert response.status_code == 503
    assert response.json()["code"] == "ingestion_queue_unavailable"
    assert "private-host" not in response.text


def test_runtime_health_exposes_configured_limits_and_model_names() -> None:
    settings = get_settings()

    response = client.get("/health/runtime")

    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "max_upload_bytes": settings.max_upload_size_bytes,
        "max_prompt_characters": settings.llm_max_total_message_chars,
        "max_completion_tokens": settings.llm_max_completion_tokens,
        "max_concurrent_requests": settings.llm_max_concurrent_requests,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "llm_model": settings.llm_model,
        "llm_adapter_id": settings.llm_adapter_id,
        "llm_adapter_sha256": settings.llm_adapter_sha256,
    }

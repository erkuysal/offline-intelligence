import asyncio

from fastapi.testclient import TestClient

from app.main import app, lifespan
from app.config import get_settings
from app.services.llm import LLMUnavailableError
from app.services.llm_readiness import LLMReadiness, llm_readiness

client = TestClient(app)


def test_llm_health_check_returns_ready_state() -> None:
    llm_readiness.set("ready")

    response = client.get("/health/llm")

    assert response.status_code == 200
    assert response.json()["service"] == "llm"
    assert response.json()["status"] == "healthy"
    assert response.json()["metadata"]["failure_type"] is None


def test_llm_health_exposes_active_adapter_identity(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_adapter_id", "adapter-v1")
    monkeypatch.setattr(get_settings(), "llm_adapter_sha256", "a" * 64)
    llm_readiness.set("ready")

    response = client.get("/health/llm")

    assert response.json()["metadata"]["adapter_id"] == "adapter-v1"
    assert response.json()["metadata"]["adapter_sha256"] == "a" * 64


def test_llm_health_check_returns_503_while_warming() -> None:
    llm_readiness.set("warming")

    response = client.get("/health/llm")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["detail"] == "LLM is warming up"


def test_llm_health_check_returns_503_when_backend_is_unavailable() -> None:
    llm_readiness.set("unavailable", "LLMUnavailableError")

    response = client.get("/health/llm")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["code"] == "llm_unavailable"
    assert response.json()["metadata"]["failure_type"] == "LLMUnavailableError"


def test_warm_up_once_marks_backend_ready(monkeypatch) -> None:
    class Backend:
        def warm_up(self, timeout_seconds: float) -> None:
            assert timeout_seconds == 2

    readiness = LLMReadiness()
    monkeypatch.setattr(
        "app.services.llm_readiness.get_llm_backend",
        lambda: Backend(),
    )

    result = asyncio.run(readiness.warm_up_once(timeout_seconds=2))

    assert result is True
    assert readiness.snapshot().status == "ready"


def test_warm_up_once_records_backend_failure(monkeypatch) -> None:
    class Backend:
        def warm_up(self, timeout_seconds: float) -> None:
            raise LLMUnavailableError("offline")

    readiness = LLMReadiness()
    monkeypatch.setattr(
        "app.services.llm_readiness.get_llm_backend",
        lambda: Backend(),
    )

    result = asyncio.run(readiness.warm_up_once(timeout_seconds=2))

    assert result is False
    assert readiness.snapshot().status == "unavailable"
    assert readiness.snapshot().error == "LLMUnavailableError"


def test_lifespan_can_disable_warmup(monkeypatch) -> None:
    monkeypatch.setattr("app.main.settings.llm_warmup_enabled", False)

    async def enter_lifespan() -> None:
        async with lifespan(app):
            assert llm_readiness.snapshot().status == "disabled"

    asyncio.run(enter_lifespan())

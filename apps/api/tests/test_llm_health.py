from fastapi.testclient import TestClient

from app.main import app
from app.services.llm import LLMTimeoutError, LLMUnavailableError

client = TestClient(app)


def test_llm_health_check_uses_fake_backend() -> None:
    response = client.get("/health/llm")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "llm": "reachable",
    }


def test_llm_health_check_returns_503_when_backend_is_unavailable(monkeypatch) -> None:
    class UnavailableBackend:
        def health_check(self) -> None:
            raise LLMUnavailableError("offline")

    monkeypatch.setattr(
        "app.main.get_llm_backend",
        lambda: UnavailableBackend(),
    )

    response = client.get("/health/llm")

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM backend is unavailable"}


def test_llm_health_check_returns_504_when_backend_times_out(monkeypatch) -> None:
    class TimeoutBackend:
        def health_check(self) -> None:
            raise LLMTimeoutError("timeout")

    monkeypatch.setattr(
        "app.main.get_llm_backend",
        lambda: TimeoutBackend(),
    )

    response = client.get("/health/llm")

    assert response.status_code == 504
    assert response.json() == {"detail": "LLM backend timed out"}

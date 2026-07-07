from fastapi.testclient import TestClient

from app.main import app
from app.schemas.chat import ChatCompletionRequest
from app.services.llm import LLMTimeoutError, LLMUnavailableError

client = TestClient(app)


def get_access_token() -> str:
    email = "chat-user@example.com"
    password = "correct-horse-battery-staple"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    return response.json()["access_token"]


def test_chat_completion_requires_authentication() -> None:
    response = client.post(
        "/api/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 401


def test_chat_completion_uses_fake_backend() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Explain Phase 2"}],
            "temperature": 0.2,
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "local-default"
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Fake LLM response: Explain Phase 2",
    }
    assert body["choices"][0]["finish_reason"] == "stop"


def test_chat_completion_rejects_streaming() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Streaming chat completions are not supported yet",
    }


def test_chat_completion_validates_message_role() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "tool", "content": "Hello"}],
        },
    )

    assert response.status_code == 422


def test_chat_completion_returns_503_when_backend_is_unavailable(monkeypatch) -> None:
    class UnavailableBackend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            raise LLMUnavailableError("offline")

    monkeypatch.setattr(
        "app.api.v1.chat.get_llm_backend",
        lambda: UnavailableBackend(),
    )
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM backend is unavailable"}


def test_chat_completion_returns_504_when_backend_times_out(monkeypatch) -> None:
    class TimeoutBackend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            raise LLMTimeoutError("timeout")

    monkeypatch.setattr(
        "app.api.v1.chat.get_llm_backend",
        lambda: TimeoutBackend(),
    )
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 504
    assert response.json() == {"detail": "LLM backend timed out"}

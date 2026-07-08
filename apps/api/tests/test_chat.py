from fastapi.testclient import TestClient

from app.api.v1.chat import llm_request_semaphore, stream_llm_response
from app.config import get_settings
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
    assert body["model"] == get_settings().llm_model
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Fake LLM response: Explain Phase 2",
    }
    assert body["choices"][0]["finish_reason"] == "stop"


def test_chat_completion_records_success_metric() -> None:
    token = get_access_token()
    before_response = client.get("/metrics")
    before_total = before_response.json()["llm_requests_total"]

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 64,
        },
    )
    after_response = client.get("/metrics")

    assert response.status_code == 200
    after_body = after_response.json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["backend"] == get_settings().llm_backend
        and request["model"] == get_settings().llm_model
        and request["outcome"] == "success"
        and request["count"] >= 1
        and request["total_latency_ms"] >= 0
        for request in after_body["llm_requests"]
    )


def test_chat_completion_streams_fake_backend() -> None:
    token = get_access_token()
    before_response = client.get("/metrics")
    before_total = before_response.json()["llm_requests_total"]

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "Hello"}], "stream": True},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: " in body
    assert "Fake LLM response: Hello" in body
    assert "data: [DONE]" in body
    after_body = client.get("/metrics").json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["backend"] == get_settings().llm_backend
        and request["model"] == get_settings().llm_model
        and request["outcome"] == "stream_success"
        and request["count"] >= 1
        for request in after_body["llm_requests"]
    )


def test_stream_cancellation_records_metric_and_releases_semaphore() -> None:
    class StreamingBackend:
        def stream_chat(self, request: ChatCompletionRequest):
            yield "data: first\n\n"
            yield "data: second\n\n"

    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )
    before_total = client.get("/metrics").json()["llm_requests_total"]
    acquired = llm_request_semaphore.acquire(blocking=False)
    assert acquired is True

    stream = stream_llm_response(StreamingBackend(), request, 0)
    assert next(stream) == "data: first\n\n"
    stream.close()

    reacquired = llm_request_semaphore.acquire(blocking=False)
    assert reacquired is True
    llm_request_semaphore.release()
    after_body = client.get("/metrics").json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["outcome"] == "stream_cancelled" and request["count"] >= 1
        for request in after_body["llm_requests"]
    )


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


def test_chat_completion_rejects_total_message_chars_over_limit(monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "llm_max_total_message_chars", 4)
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Chat messages exceed configured LLM input size limit",
    }


def test_chat_completion_rejects_max_tokens_over_limit(monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "llm_max_completion_tokens", 10)
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 11,
        },
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Requested completion tokens exceed configured LLM output limit",
    }


def test_chat_completion_returns_429_when_llm_is_busy(monkeypatch) -> None:
    was_called = False

    class Backend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            nonlocal was_called
            was_called = True

    import app.api.v1.chat as chat_module

    acquired = chat_module.llm_request_semaphore.acquire(blocking=False)
    assert acquired is True
    monkeypatch.setattr("app.api.v1.chat.get_llm_backend", lambda: Backend())
    token = get_access_token()

    try:
        response = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    finally:
        chat_module.llm_request_semaphore.release()

    assert response.status_code == 429
    assert response.json() == {"detail": "LLM backend is busy"}
    assert was_called is False


def test_chat_completion_returns_503_when_backend_is_unavailable(monkeypatch) -> None:
    class UnavailableBackend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            raise LLMUnavailableError("offline")

    monkeypatch.setattr(
        "app.api.v1.chat.get_llm_backend",
        lambda: UnavailableBackend(),
    )
    token = get_access_token()
    before_response = client.get("/metrics")
    before_total = before_response.json()["llm_requests_total"]

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM backend is unavailable"}
    after_body = client.get("/metrics").json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["outcome"] == "unavailable" and request["count"] >= 1
        for request in after_body["llm_requests"]
    )


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

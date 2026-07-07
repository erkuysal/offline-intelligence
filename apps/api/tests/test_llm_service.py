import httpx
import pytest

from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.services.llm import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    OpenAICompatibleLLMBackend,
)


def chat_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        messages=[
            ChatMessage(role="system", content="Be concise."),
            ChatMessage(role="user", content="Hello"),
        ],
        temperature=0.2,
        max_tokens=64,
    )


def test_openai_compatible_health_check_calls_models_endpoint(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:
        requested_urls.append(url)
        assert timeout == 5
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("app.services.llm.httpx.get", fake_get)
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1/",
        model="local-default",
        timeout_seconds=5,
    )

    assert backend.health_check() is True
    assert requested_urls == ["http://localhost:8080/v1/models"]


def test_openai_compatible_health_check_maps_http_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.get",
        lambda url, timeout: httpx.Response(503),
    )
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMUnavailableError):
        backend.health_check()


def test_openai_compatible_health_check_maps_timeout(monkeypatch) -> None:
    def raise_timeout(url: str, timeout: float) -> None:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.services.llm.httpx.get", raise_timeout)
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMTimeoutError):
        backend.health_check()


def test_openai_compatible_completion_posts_openai_payload(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        assert url == "http://localhost:8080/v1/chat/completions"
        assert timeout == 5
        captured_payloads.append(json)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "local-default",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from the model",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    response = backend.complete_chat(chat_request())

    assert captured_payloads == [
        {
            "model": "local-default",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
            ],
            "temperature": 0.2,
            "max_tokens": 64,
            "stream": False,
        }
    ]
    assert response.model == "local-default"
    assert response.choices[0].message.content == "Hello from the model"


def test_openai_compatible_completion_maps_server_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda url, json, timeout: httpx.Response(500),
    )
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMUnavailableError):
        backend.complete_chat(chat_request())


def test_openai_compatible_completion_maps_bad_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda url, json, timeout: httpx.Response(400),
    )
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMError):
        backend.complete_chat(chat_request())


def test_openai_compatible_completion_maps_invalid_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda url, json, timeout: httpx.Response(200, json={"not": "openai"}),
    )
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMError):
        backend.complete_chat(chat_request())


def test_openai_compatible_completion_maps_timeout(monkeypatch) -> None:
    def raise_timeout(url: str, json: dict, timeout: float) -> None:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.services.llm.httpx.post", raise_timeout)
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMTimeoutError):
        backend.complete_chat(chat_request())

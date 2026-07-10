import httpx
import pytest

from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.services.llm import (
    FakeLLMBackend,
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
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 5,
                    "total_tokens": 9,
                },
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
    assert response.usage is not None
    assert response.usage.prompt_tokens == 4
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 9


def test_openai_compatible_warmup_uses_small_request_and_timeout(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        assert timeout == 2
        captured_payloads.append(json)
        return httpx.Response(
            200,
            json={
                "model": "local-default",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Yes"},
                        "finish_reason": "length",
                    }
                ],
            },
        )

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=60,
    )

    backend.warm_up(timeout_seconds=2)

    assert captured_payloads[0]["max_tokens"] == 1
    assert captured_payloads[0]["temperature"] == 0
    assert captured_payloads[0]["stream"] is False


def test_fake_backend_returns_deterministic_usage() -> None:
    backend = FakeLLMBackend(model="local-default")

    response = backend.complete_chat(chat_request())

    assert response.usage is not None
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 7


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


def test_fake_backend_streams_openai_style_chunks() -> None:
    backend = FakeLLMBackend(model="local-default")

    chunks = list(backend.stream_chat(chat_request()))

    assert len(chunks) == 4
    assert chunks[0].startswith("data: ")
    assert "Fake LLM response: Hello" in chunks[0]
    assert '"prompt_tokens": 3' in chunks[-2]
    assert '"completion_tokens": 4' in chunks[-2]
    assert chunks[-1] == "data: [DONE]\n\n"


def test_openai_compatible_streaming_completion_proxies_sse_lines(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeStreamResponse:
        status_code = 200

        def __enter__(self) -> "FakeStreamResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def iter_lines(self) -> list[str]:
            return [
                'data: {"choices":[{"delta":{"content":"Hello"}}]}',
                "data: [DONE]",
            ]

    def fake_stream(
        method: str,
        url: str,
        json: dict,
        timeout: float,
    ) -> FakeStreamResponse:
        assert method == "POST"
        assert url == "http://localhost:8080/v1/chat/completions"
        assert timeout == 5
        captured_payloads.append(json)
        return FakeStreamResponse()

    monkeypatch.setattr("app.services.llm.httpx.stream", fake_stream)
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    chunks = list(backend.stream_chat(chat_request()))

    assert captured_payloads[0]["stream"] is True
    assert captured_payloads[0]["stream_options"] == {"include_usage": True}
    assert chunks == [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        "data: [DONE]\n\n",
    ]


def test_openai_compatible_streaming_completion_maps_server_error(monkeypatch) -> None:
    class FakeStreamResponse:
        status_code = 500

        def __enter__(self) -> "FakeStreamResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def iter_lines(self) -> list[str]:
            return []

    monkeypatch.setattr(
        "app.services.llm.httpx.stream",
        lambda method, url, json, timeout: FakeStreamResponse(),
    )
    backend = OpenAICompatibleLLMBackend(
        base_url="http://localhost:8080/v1",
        model="local-default",
        timeout_seconds=5,
    )

    with pytest.raises(LLMUnavailableError):
        list(backend.stream_chat(chat_request()))

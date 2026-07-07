from abc import ABC, abstractmethod

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
)


class LLMError(Exception):
    pass


class LLMUnavailableError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class UnsupportedLLMBackendError(LLMError):
    pass


class LLMBackend(ABC):
    @abstractmethod
    def health_check(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def complete_chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        raise NotImplementedError


class FakeLLMBackend(LLMBackend):
    def __init__(self, model: str) -> None:
        self.model = model

    def health_check(self) -> bool:
        return True

    def complete_chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        model = request.model or self.model
        latest_user_message = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            request.messages[-1].content,
        )
        return ChatCompletionResponse(
            model=model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=f"Fake LLM response: {latest_user_message}",
                    ),
                    finish_reason="stop",
                )
            ],
        )


class OpenAICompatibleLLMBackend(LLMBackend):
    def __init__(self, base_url: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def health_check(self) -> bool:
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM health check timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError("LLM backend is unavailable") from exc

        if response.status_code >= 400:
            raise LLMUnavailableError("LLM backend health check failed")

        return True

    def complete_chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        model = request.model or self.model
        payload = {
            "model": model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM completion timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError("LLM backend is unavailable") from exc

        if response.status_code >= 500:
            raise LLMUnavailableError("LLM backend returned an error")
        if response.status_code >= 400:
            raise LLMError("LLM backend rejected the request")

        try:
            data = response.json()
            return ChatCompletionResponse.model_validate(data)
        except (ValueError, ValidationError) as exc:
            raise LLMError("LLM backend returned an invalid response") from exc


def get_llm_backend() -> LLMBackend:
    settings = get_settings()
    backend = settings.llm_backend.strip().lower()

    if backend == "fake":
        return FakeLLMBackend(settings.llm_model)

    if backend in {"openai_compatible", "openai-compatible"}:
        return OpenAICompatibleLLMBackend(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    raise UnsupportedLLMBackendError(f"Unsupported LLM backend: {settings.llm_backend}")

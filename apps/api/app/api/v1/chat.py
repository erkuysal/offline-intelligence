from typing import Annotated
from collections.abc import Iterator
from threading import BoundedSemaphore
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.observability.metrics import metrics_registry
from app.schemas.chat import ChatCompletionRequest, ChatCompletionResponse, ChatUsage
from app.services.llm import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    get_llm_backend,
)
from app.services.llm import LLMBackend

router = APIRouter(prefix="/chat", tags=["chat"])
llm_request_semaphore = BoundedSemaphore(get_settings().llm_max_concurrent_requests)


def record_llm_metric(
    request: ChatCompletionRequest,
    outcome: str,
    started_at: float,
    usage: ChatUsage | None = None,
) -> None:
    settings = get_settings()
    metrics_registry.record_llm_request(
        backend=settings.llm_backend,
        model=request.model or settings.llm_model,
        outcome=outcome,
        duration_ms=round((perf_counter() - started_at) * 1000, 3),
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
    )


def validate_llm_safety_limits(request: ChatCompletionRequest) -> None:
    settings = get_settings()
    total_message_chars = sum(len(message.content) for message in request.messages)

    if total_message_chars > settings.llm_max_total_message_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Chat messages exceed configured LLM input size limit",
        )

    if request.max_tokens > settings.llm_max_completion_tokens:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Requested completion tokens exceed configured LLM output limit",
        )


def stream_llm_response(
    backend: LLMBackend,
    request: ChatCompletionRequest,
    started_at: float,
) -> Iterator[str]:
    try:
        yield from backend.stream_chat(request)
        record_llm_metric(request, "stream_success", started_at)
    except GeneratorExit:
        record_llm_metric(request, "stream_cancelled", started_at)
        raise
    except LLMTimeoutError:
        record_llm_metric(request, "stream_timeout", started_at)
        yield 'event: error\ndata: {"detail":"LLM backend timed out"}\n\n'
    except LLMUnavailableError:
        record_llm_metric(request, "stream_unavailable", started_at)
        yield 'event: error\ndata: {"detail":"LLM backend is unavailable"}\n\n'
    except LLMError:
        record_llm_metric(request, "stream_error", started_at)
        yield 'event: error\ndata: {"detail":"LLM backend returned an invalid response"}\n\n'
    finally:
        llm_request_semaphore.release()


@router.post("/completions", response_model=None)
def create_chat_completion(
    request: ChatCompletionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatCompletionResponse | StreamingResponse:
    started_at = perf_counter()

    try:
        validate_llm_safety_limits(request)
    except HTTPException:
        record_llm_metric(request, "safety_rejected", started_at)
        raise

    backend = get_llm_backend()

    if not llm_request_semaphore.acquire(blocking=False):
        record_llm_metric(request, "busy", started_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM backend is busy",
        )

    if request.stream:
        return StreamingResponse(
            stream_llm_response(backend, request, started_at),
            media_type="text/event-stream",
        )

    try:
        response = backend.complete_chat(request)
        record_llm_metric(request, "success", started_at, response.usage)
        return response
    except LLMTimeoutError as exc:
        record_llm_metric(request, "timeout", started_at)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM backend timed out",
        ) from exc
    except LLMUnavailableError as exc:
        record_llm_metric(request, "unavailable", started_at)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM backend is unavailable",
        ) from exc
    except LLMError as exc:
        record_llm_metric(request, "error", started_at)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM backend returned an invalid response",
        ) from exc
    finally:
        llm_request_semaphore.release()

from typing import Annotated
from threading import BoundedSemaphore
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.observability.metrics import metrics_registry
from app.schemas.chat import ChatCompletionRequest, ChatCompletionResponse
from app.services.llm import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    get_llm_backend,
)

router = APIRouter(prefix="/chat", tags=["chat"])
llm_request_semaphore = BoundedSemaphore(get_settings().llm_max_concurrent_requests)


def record_llm_metric(
    request: ChatCompletionRequest,
    outcome: str,
    started_at: float,
) -> None:
    settings = get_settings()
    metrics_registry.record_llm_request(
        backend=settings.llm_backend,
        model=request.model or settings.llm_model,
        outcome=outcome,
        duration_ms=round((perf_counter() - started_at) * 1000, 3),
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


@router.post("/completions", response_model=ChatCompletionResponse)
def create_chat_completion(
    request: ChatCompletionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatCompletionResponse:
    started_at = perf_counter()

    if request.stream:
        record_llm_metric(request, "stream_unsupported", started_at)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming chat completions are not supported yet",
        )

    try:
        validate_llm_safety_limits(request)
    except HTTPException:
        record_llm_metric(request, "safety_rejected", started_at)
        raise

    if not llm_request_semaphore.acquire(blocking=False):
        record_llm_metric(request, "busy", started_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM backend is busy",
        )

    try:
        response = get_llm_backend().complete_chat(request)
        record_llm_metric(request, "success", started_at)
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

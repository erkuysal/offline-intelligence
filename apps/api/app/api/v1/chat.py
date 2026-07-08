from typing import Annotated
from threading import BoundedSemaphore

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.chat import ChatCompletionRequest, ChatCompletionResponse
from app.services.llm import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    get_llm_backend,
)

router = APIRouter(prefix="/chat", tags=["chat"])
llm_request_semaphore = BoundedSemaphore(get_settings().llm_max_concurrent_requests)


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
    if request.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming chat completions are not supported yet",
        )

    validate_llm_safety_limits(request)

    if not llm_request_semaphore.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM backend is busy",
        )

    try:
        return get_llm_backend().complete_chat(request)
    except LLMTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM backend timed out",
        ) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM backend is unavailable",
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM backend returned an invalid response",
        ) from exc
    finally:
        llm_request_semaphore.release()

from typing import Annotated
from collections.abc import Iterator
import json
from threading import BoundedSemaphore
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.conversation import Conversation, ConversationMessage
from app.models.user import User
from app.observability.metrics import metrics_registry
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatSource,
    ChatUsage,
    ConversationMessageRead,
    ConversationRead,
)
from app.services.conversations import persist_chat_exchange
from app.services.embeddings import EmbeddingError
from app.services.llm import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    estimate_tokens,
    get_llm_backend,
)
from app.services.llm import LLMBackend
from app.services.rag import augment_chat_request

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
    sources: list[ChatSource] | None = None,
    *,
    db: Session | None = None,
    owner_id: int | None = None,
    persistence_request: ChatCompletionRequest | None = None,
) -> Iterator[str]:
    usage: ChatUsage | None = None
    streamed_content: list[str] = []
    metrics_registry.record_llm_started()
    try:
        if sources:
            source_data = [source.model_dump() for source in sources]
            yield f"event: sources\ndata: {json.dumps(source_data, separators=(',', ':'))}\n\n"
        for event in backend.stream_chat(request):
            event_usage, content = parse_stream_event(event)
            if event_usage is not None:
                usage = event_usage
            if content:
                streamed_content.append(content)
            if not is_done_event(event):
                yield event
        if usage is None:
            prompt_tokens = estimate_tokens(" ".join(message.content for message in request.messages))
            completion_tokens = estimate_tokens("".join(streamed_content)) if streamed_content else 0
            usage = ChatUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )
        conversation_id: int | None = None
        if db is not None and owner_id is not None and persistence_request is not None:
            conversation = persist_chat_exchange(
                db,
                owner_id=owner_id,
                request=persistence_request,
                assistant_content="".join(streamed_content),
                sources=sources or [],
                model=request.model or get_settings().llm_model,
                usage=usage,
            )
            conversation_id = conversation.id
        completion_data = {
            "conversation_id": conversation_id,
            "model": request.model or get_settings().llm_model,
            "usage": usage.model_dump(),
        }
        yield f"event: complete\ndata: {json.dumps(completion_data, separators=(',', ':'))}\n\n"
        yield "data: [DONE]\n\n"
        record_llm_metric(request, "stream_success", started_at, usage)
    except GeneratorExit:
        record_llm_metric(request, "stream_cancelled", started_at)
        raise
    except LLMTimeoutError:
        record_llm_metric(request, "stream_timeout", started_at)
        yield stream_error_event("llm_timeout", "LLM backend timed out", retryable=True)
    except LLMUnavailableError:
        record_llm_metric(request, "stream_unavailable", started_at)
        yield stream_error_event("llm_unavailable", "LLM backend is unavailable", retryable=True)
    except LLMError:
        record_llm_metric(request, "stream_error", started_at)
        yield stream_error_event(
            "llm_invalid_response",
            "LLM backend returned an invalid response",
            retryable=False,
        )
    finally:
        metrics_registry.record_llm_finished()
        llm_request_semaphore.release()


def is_done_event(event: str) -> bool:
    return any(
        line.removeprefix("data:").strip() == "[DONE]"
        for line in event.splitlines()
        if line.startswith("data:")
    )


def stream_error_event(code: str, detail: str, *, retryable: bool) -> str:
    data = {"code": code, "detail": detail, "retryable": retryable}
    return f"event: error\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def parse_stream_event(event: str) -> tuple[ChatUsage | None, str | None]:
    usage: ChatUsage | None = None
    content: str | None = None
    for line in event.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue

        raw_usage = data.get("usage")
        if raw_usage is not None:
            try:
                usage = ChatUsage.model_validate(raw_usage)
            except ValueError:
                pass

        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                content = delta["content"]
    return usage, content


@router.post("/completions", response_model=None)
def create_chat_completion(
    request: ChatCompletionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatCompletionResponse | StreamingResponse:
    started_at = perf_counter()

    try:
        validate_llm_safety_limits(request)
    except HTTPException:
        record_llm_metric(request, "safety_rejected", started_at)
        raise

    if request.conversation_id is not None:
        conversation = db.get(Conversation, request.conversation_id)
        if conversation is None or conversation.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

    try:
        rag_context = augment_chat_request(
            db,
            owner_id=current_user.id,
            request=request,
            settings=settings,
        )
    except EmbeddingError as exc:
        record_llm_metric(request, "retrieval_error", started_at)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document retrieval backend is unavailable",
        ) from exc

    backend = get_llm_backend()

    if not llm_request_semaphore.acquire(blocking=False):
        record_llm_metric(request, "busy", started_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM backend is busy",
        )

    if request.stream:
        return StreamingResponse(
            stream_llm_response(
                backend,
                rag_context.request,
                started_at,
                rag_context.sources,
                db=db,
                owner_id=current_user.id,
                persistence_request=request,
            ),
            media_type="text/event-stream",
        )

    metrics_registry.record_llm_started()
    try:
        response = backend.complete_chat(rag_context.request)
        if rag_context.sources:
            response.sources = rag_context.sources
        try:
            conversation = persist_chat_exchange(
                db,
                owner_id=current_user.id,
                request=request,
                assistant_content=response.choices[0].message.content,
                sources=rag_context.sources,
                model=response.model,
                usage=response.usage,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            ) from exc
        response.conversation_id = conversation.id
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
        metrics_registry.record_llm_finished()
        llm_request_semaphore.release()


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.owner_id == current_user.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageRead])
def list_conversation_messages(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ConversationMessage]:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return list(conversation.messages)

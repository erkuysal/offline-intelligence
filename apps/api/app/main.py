import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated
import logging
from time import perf_counter

from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.router import api_router
from app.cache.redis import ping_redis
from app.config import get_settings
from app.db.session import get_db
from app.observability.logging import configure_logging, log_event
from app.observability.metrics import metrics_registry
from app.schemas.system import MetadataValue, ServiceHealthResponse, ServiceStatus
from app.services.embeddings import EmbeddingError, get_embedding_provider
from app.services.llm_readiness import llm_readiness

settings = get_settings()
configure_logging()
request_logger = logging.getLogger("app.requests")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    warmup_task: asyncio.Task[None] | None = None
    if settings.llm_warmup_enabled:
        warmup_task = asyncio.create_task(
            llm_readiness.run(
                timeout_seconds=settings.llm_warmup_timeout_seconds,
                retry_seconds=settings.llm_warmup_retry_seconds,
            )
        )
    else:
        llm_readiness.set("disabled")

    yield

    if warmup_task is not None:
        warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await warmup_task


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)
app.include_router(api_router)


@app.middleware("http")
async def request_observability(
    request: Request,
    call_next,
) -> Response:
    started_at = perf_counter()
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        route = request.scope.get("route")
        metric_path = getattr(route, "path", request.url.path)
        metrics_registry.record_request(
            method=request.method,
            path=metric_path,
            status_code=status_code,
        )
        log_event(
            request_logger,
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_host=request.client.host if request.client else None,
        )


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


def service_health(
    service: str,
    service_status: ServiceStatus,
    detail: str,
    *,
    code: str | None = None,
    metadata: dict[str, MetadataValue] | None = None,
) -> ServiceHealthResponse:
    return ServiceHealthResponse(
        service=service,
        status=service_status,
        detail=detail,
        code=code,
        checked_at=datetime.now(UTC),
        metadata=metadata or {},
    )


@app.get("/health", tags=["system"], response_model=ServiceHealthResponse)
async def health_check() -> ServiceHealthResponse:
    return service_health(
        "api",
        "healthy",
        "API is accepting requests",
        metadata={"version": settings.app_version, "environment": settings.environment},
    )


@app.get("/health/db", tags=["system"], response_model=ServiceHealthResponse)
def database_health_check(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> ServiceHealthResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return service_health(
            "database",
            "unavailable",
            "Database connection failed",
            code="database_unavailable",
        )

    return service_health("database", "healthy", "Database is reachable")


@app.get("/health/redis", tags=["system"], response_model=ServiceHealthResponse)
def redis_health_check(response: Response) -> ServiceHealthResponse:
    try:
        ping_redis()
    except RedisError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return service_health(
            "redis",
            "unavailable",
            "Redis connection failed",
            code="redis_unavailable",
        )

    return service_health("redis", "healthy", "Redis is reachable")


@app.get("/health/llm", tags=["system"], response_model=ServiceHealthResponse)
def llm_health_check(response: Response) -> ServiceHealthResponse:
    snapshot = llm_readiness.snapshot()
    status_map: dict[str, ServiceStatus] = {
        "ready": "healthy",
        "warming": "degraded",
        "unavailable": "unavailable",
        "disabled": "disabled",
    }
    service_status = status_map[snapshot.status]
    if service_status in {"degraded", "unavailable"}:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    details = {
        "ready": "LLM is ready",
        "warming": "LLM is warming up",
        "unavailable": "LLM backend is unavailable",
        "disabled": "LLM warm-up is disabled",
    }
    return service_health(
        "llm",
        service_status,
        details[snapshot.status],
        code="llm_unavailable" if snapshot.status == "unavailable" else None,
        metadata={
            "backend": settings.llm_backend,
            "model": settings.llm_model,
            "adapter_id": settings.llm_adapter_id or None,
            "adapter_sha256": settings.llm_adapter_sha256 or None,
            "last_check": snapshot.checked_at,
            "failure_type": snapshot.error,
        },
    )


@app.get("/health/embedding", tags=["system"], response_model=ServiceHealthResponse)
def embedding_health_check(response: Response) -> ServiceHealthResponse:
    try:
        provider = get_embedding_provider()
        embeddings = provider.embed_texts(["health check"])
        if len(embeddings) != 1 or len(embeddings[0]) != settings.embedding_dimensions:
            raise EmbeddingError("Embedding dimensions do not match configuration")
    except EmbeddingError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return service_health(
            "embedding",
            "unavailable",
            "Embedding backend health check failed",
            code="embedding_unavailable",
            metadata={"backend": settings.embedding_backend, "model": settings.embedding_model},
        )
    return service_health(
        "embedding",
        "healthy",
        "Embedding backend is ready",
        metadata={
            "backend": settings.embedding_backend,
            "model": provider.model,
            "dimensions": provider.dimensions,
        },
    )


@app.get("/health/worker", tags=["system"], response_model=ServiceHealthResponse)
def worker_health_check(response: Response) -> ServiceHealthResponse:
    if settings.document_ingestion_mode == "sync":
        return service_health(
            "worker",
            "healthy",
            "Document ingestion runs in the API process",
            metadata={"mode": "sync"},
        )
    try:
        ping_redis()
    except RedisError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return service_health(
            "worker",
            "unavailable",
            "Document ingestion queue is unavailable",
            code="ingestion_queue_unavailable",
            metadata={"mode": settings.document_ingestion_mode},
        )
    return service_health(
        "worker",
        "degraded",
        "Ingestion queue is reachable; worker heartbeat is not configured",
        code="worker_heartbeat_unavailable",
        metadata={"mode": settings.document_ingestion_mode},
    )


@app.get("/health/runtime", tags=["system"], response_model=ServiceHealthResponse)
def runtime_configuration() -> ServiceHealthResponse:
    return service_health(
        "runtime",
        "healthy",
        "Runtime limits and model identities are loaded",
        metadata={
            "max_upload_bytes": settings.max_upload_size_bytes,
            "max_prompt_characters": settings.llm_max_total_message_chars,
            "max_completion_tokens": settings.llm_max_completion_tokens,
            "max_concurrent_requests": settings.llm_max_concurrent_requests,
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "llm_model": settings.llm_model,
            "llm_adapter_id": settings.llm_adapter_id or None,
            "llm_adapter_sha256": settings.llm_adapter_sha256 or None,
        },
    )


@app.get("/metrics", tags=["system"])
async def metrics() -> Response:
    return Response(
        content=generate_latest(metrics_registry.prometheus_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/metrics.json", tags=["system"])
async def metrics_json() -> dict[str, object]:
    snapshot = metrics_registry.snapshot(
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.environment,
    )
    snapshot["llm_readiness"] = llm_readiness.snapshot().as_dict()
    return snapshot


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()

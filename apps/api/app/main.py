import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated
import logging
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
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
        metrics_registry.record_request(
            method=request.method,
            path=request.url.path,
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


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/health/db", tags=["system"])
def database_health_check(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return {
        "status": "healthy",
        "database": "reachable",
    }


@app.get("/health/redis", tags=["system"])
def redis_health_check() -> dict[str, str]:
    try:
        ping_redis()
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable",
        ) from exc

    return {
        "status": "healthy",
        "redis": "reachable",
    }


@app.get("/health/llm", tags=["system"])
def llm_health_check(response: Response) -> dict[str, str | None]:
    snapshot = llm_readiness.snapshot()
    if snapshot.status not in {"ready", "disabled"}:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot.as_dict()


@app.get("/metrics", tags=["system"])
async def metrics() -> dict[str, object]:
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

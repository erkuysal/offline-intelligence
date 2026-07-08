from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Literal

from app.observability.metrics import metrics_registry
from app.services.llm import LLMError, get_llm_backend

ReadinessStatus = Literal["disabled", "warming", "ready", "unavailable"]


@dataclass(frozen=True)
class LLMReadinessSnapshot:
    status: ReadinessStatus
    checked_at: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


class LLMReadiness:
    def __init__(self) -> None:
        self._snapshot = LLMReadinessSnapshot(status="warming")
        self._lock = Lock()

    def snapshot(self) -> LLMReadinessSnapshot:
        with self._lock:
            return self._snapshot

    def set(self, status: ReadinessStatus, error: str | None = None) -> None:
        with self._lock:
            self._snapshot = LLMReadinessSnapshot(
                status=status,
                checked_at=datetime.now(UTC).isoformat(),
                error=error,
            )

    async def warm_up_once(self, timeout_seconds: float) -> bool:
        self.set("warming")
        started_at = perf_counter()
        outcome = "success"
        try:
            backend = get_llm_backend()
            await asyncio.to_thread(backend.warm_up, timeout_seconds)
        except LLMError as exc:
            outcome = "failure"
            self.set("unavailable", type(exc).__name__)
            return False
        except Exception as exc:
            outcome = "failure"
            self.set("unavailable", type(exc).__name__)
            return False
        finally:
            metrics_registry.record_llm_warmup(
                outcome=outcome,
                duration_ms=(perf_counter() - started_at) * 1000,
            )

        self.set("ready")
        return True

    async def run(
        self,
        timeout_seconds: float,
        retry_seconds: float,
    ) -> None:
        while True:
            if await self.warm_up_once(timeout_seconds):
                return
            await asyncio.sleep(retry_seconds)


llm_readiness = LLMReadiness()

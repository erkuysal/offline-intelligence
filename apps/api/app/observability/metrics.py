from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RequestMetric:
    method: str
    path: str
    status_code: int


@dataclass(frozen=True)
class LLMMetric:
    backend: str
    model: str
    outcome: str


class MetricsRegistry:
    def __init__(self) -> None:
        self._started_at = monotonic()
        self._total_requests = 0
        self._requests: Counter[RequestMetric] = Counter()
        self._total_llm_requests = 0
        self._llm_requests: Counter[LLMMetric] = Counter()
        self._llm_latency_ms: Counter[LLMMetric] = Counter()
        self._llm_prompt_tokens: Counter[LLMMetric] = Counter()
        self._llm_completion_tokens: Counter[LLMMetric] = Counter()
        self._llm_total_tokens: Counter[LLMMetric] = Counter()
        self._llm_warmup_attempts: Counter[str] = Counter()
        self._llm_warmup_latency_ms: Counter[str] = Counter()
        self._lock = Lock()

    def record_request(self, method: str, path: str, status_code: int) -> None:
        metric = RequestMetric(
            method=method,
            path=path,
            status_code=status_code,
        )
        with self._lock:
            self._total_requests += 1
            self._requests[metric] += 1

    def record_llm_request(
        self,
        backend: str,
        model: str,
        outcome: str,
        duration_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        metric = LLMMetric(
            backend=backend,
            model=model,
            outcome=outcome,
        )
        with self._lock:
            self._total_llm_requests += 1
            self._llm_requests[metric] += 1
            self._llm_latency_ms[metric] += duration_ms
            self._llm_prompt_tokens[metric] += prompt_tokens
            self._llm_completion_tokens[metric] += completion_tokens
            self._llm_total_tokens[metric] += total_tokens

    def record_llm_warmup(self, outcome: str, duration_ms: float) -> None:
        with self._lock:
            self._llm_warmup_attempts[outcome] += 1
            self._llm_warmup_latency_ms[outcome] += duration_ms

    def snapshot(
        self,
        app_name: str,
        app_version: str,
        environment: str,
    ) -> dict[str, object]:
        with self._lock:
            requests = [
                {
                    "method": metric.method,
                    "path": metric.path,
                    "status_code": metric.status_code,
                    "count": count,
                }
                for metric, count in self._requests.items()
            ]
            total_requests = self._total_requests
            llm_requests = [
                {
                    "backend": metric.backend,
                    "model": metric.model,
                    "outcome": metric.outcome,
                    "count": count,
                    "total_latency_ms": round(self._llm_latency_ms[metric], 3),
                    "prompt_tokens": self._llm_prompt_tokens[metric],
                    "completion_tokens": self._llm_completion_tokens[metric],
                    "total_tokens": self._llm_total_tokens[metric],
                }
                for metric, count in self._llm_requests.items()
            ]
            total_llm_requests = self._total_llm_requests
            llm_warmups = [
                {
                    "outcome": outcome,
                    "count": count,
                    "total_latency_ms": round(self._llm_warmup_latency_ms[outcome], 3),
                }
                for outcome, count in self._llm_warmup_attempts.items()
            ]

        return {
            "app": {
                "name": app_name,
                "version": app_version,
                "environment": environment,
            },
            "uptime_seconds": round(monotonic() - self._started_at, 6),
            "requests_total": total_requests,
            "requests": sorted(
                requests,
                key=lambda item: (
                    str(item["path"]),
                    str(item["method"]),
                    int(item["status_code"]),
                ),
            ),
            "llm_requests_total": total_llm_requests,
            "llm_requests": sorted(
                llm_requests,
                key=lambda item: (
                    str(item["backend"]),
                    str(item["model"]),
                    str(item["outcome"]),
                ),
            ),
            "llm_warmups": sorted(llm_warmups, key=lambda item: str(item["outcome"])),
        }


metrics_registry = MetricsRegistry()

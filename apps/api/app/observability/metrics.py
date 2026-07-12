from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import cast

from prometheus_client import CollectorRegistry, Counter as PrometheusCounter, Gauge, Histogram


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


@dataclass(frozen=True)
class OperationMetric:
    stage: str
    operation: str
    outcome: str


class MetricsRegistry:
    def __init__(self) -> None:
        self.prometheus_registry = CollectorRegistry()
        self._started_at = monotonic()
        self._total_requests = 0
        self._requests: Counter[RequestMetric] = Counter()
        self._total_llm_requests = 0
        self._llm_requests: Counter[LLMMetric] = Counter()
        self._llm_latency_ms: defaultdict[LLMMetric, float] = defaultdict(float)
        self._llm_prompt_tokens: Counter[LLMMetric] = Counter()
        self._llm_completion_tokens: Counter[LLMMetric] = Counter()
        self._llm_total_tokens: Counter[LLMMetric] = Counter()
        self._llm_warmup_attempts: Counter[str] = Counter()
        self._llm_warmup_latency_ms: defaultdict[str, float] = defaultdict(float)
        self._operations: Counter[OperationMetric] = Counter()
        self._operation_latency_ms: defaultdict[OperationMetric, float] = defaultdict(float)
        self._operation_items: Counter[OperationMetric] = Counter()
        self._lock = Lock()
        self.http_requests = PrometheusCounter(
            "offline_hub_http_requests",
            "HTTP requests processed by the API.",
            ("method", "path", "status_code"),
            registry=self.prometheus_registry,
        )
        self.llm_requests = PrometheusCounter(
            "offline_hub_llm_requests",
            "LLM requests by backend, model, and outcome.",
            ("backend", "model", "outcome"),
            registry=self.prometheus_registry,
        )
        self.llm_request_duration = Histogram(
            "offline_hub_llm_request_duration_seconds",
            "End-to-end LLM request duration in seconds.",
            ("backend", "model", "outcome"),
            registry=self.prometheus_registry,
        )
        self.llm_tokens = PrometheusCounter(
            "offline_hub_llm_tokens",
            "Tokens processed by completed LLM requests.",
            ("backend", "model", "type"),
            registry=self.prometheus_registry,
        )
        self.llm_active_requests = Gauge(
            "offline_hub_llm_active_requests",
            "LLM requests currently holding a concurrency slot.",
            registry=self.prometheus_registry,
        )
        self.llm_rejections = PrometheusCounter(
            "offline_hub_llm_rejections",
            "LLM requests rejected before inference.",
            ("reason",),
            registry=self.prometheus_registry,
        )
        self.llm_warmup_attempts = PrometheusCounter(
            "offline_hub_llm_warmup_attempts",
            "LLM warm-up attempts by outcome.",
            ("outcome",),
            registry=self.prometheus_registry,
        )
        self.llm_warmup_duration = Histogram(
            "offline_hub_llm_warmup_duration_seconds",
            "LLM warm-up duration in seconds.",
            ("outcome",),
            registry=self.prometheus_registry,
        )
        self.operations = PrometheusCounter(
            "offline_hub_operations",
            "Backend operations by stage, operation, and outcome.",
            ("stage", "operation", "outcome"),
            registry=self.prometheus_registry,
        )
        self.operation_duration = Histogram(
            "offline_hub_operation_duration_seconds",
            "Backend operation duration in seconds.",
            ("stage", "operation", "outcome"),
            registry=self.prometheus_registry,
        )
        self.operation_items = PrometheusCounter(
            "offline_hub_operation_items",
            "Items processed or returned by backend operations.",
            ("stage", "operation", "outcome"),
            registry=self.prometheus_registry,
        )

    def record_request(self, method: str, path: str, status_code: int) -> None:
        metric = RequestMetric(
            method=method,
            path=path,
            status_code=status_code,
        )
        with self._lock:
            self._total_requests += 1
            self._requests[metric] += 1
        self.http_requests.labels(method=method, path=path, status_code=str(status_code)).inc()

    def record_llm_started(self) -> None:
        self.llm_active_requests.inc()

    def record_llm_finished(self) -> None:
        self.llm_active_requests.dec()

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
        labels = {"backend": backend, "model": model, "outcome": outcome}
        self.llm_requests.labels(**labels).inc()
        self.llm_request_duration.labels(**labels).observe(duration_ms / 1000)
        self.llm_tokens.labels(backend=backend, model=model, type="prompt").inc(prompt_tokens)
        self.llm_tokens.labels(backend=backend, model=model, type="completion").inc(completion_tokens)
        self.llm_tokens.labels(backend=backend, model=model, type="total").inc(total_tokens)
        if outcome in {"busy", "safety_rejected"}:
            self.llm_rejections.labels(reason=outcome).inc()

    def record_llm_warmup(self, outcome: str, duration_ms: float) -> None:
        with self._lock:
            self._llm_warmup_attempts[outcome] += 1
            self._llm_warmup_latency_ms[outcome] += duration_ms
        self.llm_warmup_attempts.labels(outcome=outcome).inc()
        self.llm_warmup_duration.labels(outcome=outcome).observe(duration_ms / 1000)

    def record_operation(
        self,
        *,
        stage: str,
        operation: str,
        outcome: str,
        duration_ms: float,
        item_count: int = 0,
    ) -> None:
        metric = OperationMetric(stage=stage, operation=operation, outcome=outcome)
        with self._lock:
            self._operations[metric] += 1
            self._operation_latency_ms[metric] += duration_ms
            self._operation_items[metric] += item_count
        labels = {"stage": stage, "operation": operation, "outcome": outcome}
        self.operations.labels(**labels).inc()
        self.operation_duration.labels(**labels).observe(duration_ms / 1000)
        self.operation_items.labels(**labels).inc(item_count)

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
            operations = [
                {
                    "stage": metric.stage,
                    "operation": metric.operation,
                    "outcome": metric.outcome,
                    "count": count,
                    "total_latency_ms": round(self._operation_latency_ms[metric], 3),
                    "item_count": self._operation_items[metric],
                }
                for metric, count in self._operations.items()
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
                    cast(int, item["status_code"]),
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
            "operations": sorted(
                operations,
                key=lambda item: (
                    str(item["stage"]),
                    str(item["operation"]),
                    str(item["outcome"]),
                ),
            ),
        }


metrics_registry = MetricsRegistry()

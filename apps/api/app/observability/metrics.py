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


class MetricsRegistry:
    def __init__(self) -> None:
        self._started_at = monotonic()
        self._total_requests = 0
        self._requests: Counter[RequestMetric] = Counter()
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
        }


metrics_registry = MetricsRegistry()

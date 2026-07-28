"""Small dependency-free Prometheus metrics registry."""

from __future__ import annotations

import threading
from collections import Counter


class RequestMetrics:
    """Track bounded HTTP status/method counters and total latency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[tuple[str, int]] = Counter()
        self._duration_seconds = 0.0

    def observe(self, *, method: str, status: int, duration_seconds: float) -> None:
        normalized_method = method.upper() if method else "UNKNOWN"
        with self._lock:
            self._requests[(normalized_method, status)] += 1
            self._duration_seconds += max(0.0, duration_seconds)

    def render(self) -> str:
        with self._lock:
            items = sorted(self._requests.items())
            duration = self._duration_seconds
            total = sum(self._requests.values())
        lines = [
            "# HELP bookflow_http_requests_total HTTP responses by method and status.",
            "# TYPE bookflow_http_requests_total counter",
        ]
        lines.extend(
            f'bookflow_http_requests_total{{method="{method}",status="{status}"}} {count}'
            for (method, status), count in items
        )
        lines.extend(
            (
                "# HELP bookflow_http_request_duration_seconds_total Total HTTP response time.",
                "# TYPE bookflow_http_request_duration_seconds_total counter",
                f"bookflow_http_request_duration_seconds_total {duration:.6f}",
                "# HELP bookflow_http_requests_observed Number of observed HTTP responses.",
                "# TYPE bookflow_http_requests_observed counter",
                f"bookflow_http_requests_observed {total}",
            )
        )
        return "\n".join(lines) + "\n"

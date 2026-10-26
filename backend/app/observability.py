"""Low-cardinality Prometheus instruments for the QueueForge control plane."""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "queueforge_http_requests_total",
    "HTTP requests handled by the QueueForge API.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "queueforge_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_IN_PROGRESS = Gauge(
    "queueforge_http_requests_in_progress",
    "HTTP requests currently executing.",
    ("method",),
)
JOBS_TOTAL = Gauge(
    "queueforge_jobs_total",
    "Current aggregate jobs by state across the service.",
    ("status",),
)
METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST


def metrics_payload() -> bytes:
    return generate_latest()

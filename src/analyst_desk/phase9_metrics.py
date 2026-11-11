"""Phase 9B: bounded-cardinality, single-worker Prometheus instrumentation.

No thread IDs, filing text, query text, company names, model outputs, or secrets
are stored as metric labels.  This module does not assert financial or semantic
verification: the verified-number ratio is unavailable until actual numerator
and denominator events exist in the verification pipeline.

Single-process mode only.  For multiple Uvicorn workers, configure the
prometheus_client multiprocess collector rather than importing these metrics
unchanged.  Use one Uvicorn worker for the Phase 9B local validation.
"""
from __future__ import annotations

from time import perf_counter

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "analystdesk_http_requests_total",
    "HTTP requests completed (SSE HTTP 200 does not imply research success).",
    ["route", "method", "status"], registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "analystdesk_http_request_duration_seconds",
    "HTTP request lifetime, including streaming response completion.",
    ["route", "method"], registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
RESEARCH_RUNS = Counter(
    "analystdesk_research_runs_total",
    "Offline audited research outcomes, including errors delivered after HTTP 200.",
    ["outcome"], registry=REGISTRY,
)
RESEARCH_DURATION = Histogram(
    "analystdesk_research_duration_seconds",
    "Elapsed time of admitted offline audited research runs.",
    ["outcome"], registry=REGISTRY,
    buckets=(0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)
CITATIONS_PER_RUN = Histogram(
    "analystdesk_research_citations_per_run",
    "Number of source citation IDs returned by a successful audited research run (not entailment checks).",
    registry=REGISTRY, buckets=(0, 1, 5, 10, 20, 50, 100, 250),
)
XBRL_FACTS_PER_RUN = Histogram(
    "analystdesk_research_xbrl_facts_per_run",
    "Number of XBRL fact IDs returned by a successful audited research run (not numeric verification).",
    registry=REGISTRY, buckets=(0, 1, 5, 10, 20, 50, 100, 250),
)

_ALLOWED_ROUTES = frozenset(("/healthz", "/v1/research/stream"))


class HTTPMetricsMiddleware:
    """Pure ASGI middleware: observes the entire SSE response, not just headers.

    /metrics excludes itself to avoid scrapes modifying their own counters.
    Unknown paths collapse to a single finite-cardinality `_other` route.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        route = path if path in _ALLOWED_ROUTES else "_other"
        method = scope.get("method", "").upper()
        method = method if method in ("GET", "POST") else "OTHER"
        started = perf_counter()
        status = 500

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except BaseException:
            # The HTTP headers may already have gone out with 200.  A
            # transport-level exception is separately counted as a failure.
            status = 500
            raise
        finally:
            HTTP_REQUESTS.labels(route=route, method=method, status=str(status)).inc()
            HTTP_DURATION.labels(route=route, method=method).observe(perf_counter() - started)

"""Phase 9B: local, audited research SSE with Prometheus metrics.

Reuses the existing approved-plan Stage 4B3 runner; no planner, approval
changes, live LLM synthesis, or report publishing. Run on 127.0.0.1 until
an authenticated deployment gateway is implemented and tested.
"""
from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Annotated

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from .phase9_metrics import (
    CITATIONS_PER_RUN, HTTPMetricsMiddleware, REGISTRY, RESEARCH_DURATION,
    RESEARCH_RUNS, XBRL_FACTS_PER_RUN,
)

app = FastAPI(title="AnalystDesk", version="0.1.0", docs_url=None, redoc_url=None)
app.add_middleware(HTTPMetricsMiddleware)

# Only one active research run per application worker.  Phase 9B is
# single-process/local; a distributed lock would be needed for multi-worker use.
_research_lock = asyncio.Lock()


class AuditedResearchRequest(BaseModel):
    thread_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


def _sse(event: str, data: dict) -> str:
    """Serialize structured events without revealing raw error or filing text."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'), ensure_ascii=True)}\n\n"


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "UP", "component": "phase9a_api"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    # Not authenticated: local-only endpoint. No raw source text or PII labels.
    return Response(content=generate_latest(REGISTRY), headers={
        "Content-Type": CONTENT_TYPE_LATEST,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })


@app.post("/v1/research/stream")
async def stream_research(request: AuditedResearchRequest) -> StreamingResponse:
    """Stream the existing offline, pre-approved Stage 4B3 research lifecycle."""
    async def events():
        if _research_lock.locked():
            RESEARCH_RUNS.labels(outcome="busy").inc()
            yield _sse("error", {"status": "BUSY", "code": "RESEARCH_ALREADY_RUNNING"})
            return

        async with _research_lock:
            started = perf_counter()
            outcome = "error"  # Fail closed if runner or serialization fails.
            try:
                yield _sse("started", {"status": "RUNNING", "phase": "STAGE4B3",
                                       "thread_id": request.thread_id, "llm_enabled": False})
                from .stage4a_config import PROJECT_ROOT
                from .stage4b3_cli import run as run_b3

                result = await run_b3(PROJECT_ROOT, request.thread_id, no_llm=True)
                # A successful HTTP 200 is NOT evidence of a completed or
                # safe run. Enforce the existing audited-run contract.
                if (result.get("status") != "PASS" or
                        result.get("approved_plan_consumed") is not True or
                        result.get("llm_synthesis_performed") is not False or
                        result.get("publication_performed") is not False):
                    raise ValueError("Audited research contract not satisfied")

                citations = result["citation_count"]
                facts = result["xbrl_fact_count"]
                if (type(citations) is not int or citations < 0 or
                        type(facts) is not int or facts < 0):
                    raise ValueError("Audited research count contract not satisfied")

                event = {
                    "status": "PASS", "phase": result["phase"],
                    "approved_plan_consumed": True,
                    "citation_count": citations, "xbrl_fact_count": facts,
                    "llm_synthesis_performed": False,
                    "publication_performed": False,
                }
                # Only count legitimate, completed research as success.
                CITATIONS_PER_RUN.observe(citations)
                XBRL_FACTS_PER_RUN.observe(facts)
                outcome = "success"
                yield _sse("completed", event)
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except Exception:
                # No raw exception, credentials, passages, or model text in SSE.
                yield _sse("error", {"status": "ERROR", "code": "RESEARCH_EXECUTION_FAILED"})
            finally:
                RESEARCH_RUNS.labels(outcome=outcome).inc()
                RESEARCH_DURATION.labels(outcome=outcome).observe(perf_counter() - started)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store",
        "X-Accel-Buffering": "no",
        "X-Content-Type-Options": "nosniff",
    })

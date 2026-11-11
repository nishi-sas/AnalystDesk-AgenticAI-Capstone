"""Phase 9B: no network or model calls; exercise ASGI and SSE observability."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient
from analyst_desk.phase9_api import app


def _metric(text: str, metric: str, labels: str) -> float:
    line = re.search(rf"^{re.escape(metric)}\{{{labels}\}}\s+(\d+(?:\.\d+)?)$", text, re.M)
    assert line is not None, (metric, labels)
    return float(line.group(1))


def test_prometheus_endpoint_is_local_only_and_no_source_content():
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert "analystdesk_research_runs_total" in response.text or "analystdesk_http_requests_total" in response.text
    assert "secret-canary" not in response.text
    assert "thread_id" not in response.text


def test_health_requests_increment_count_without_metric_self_scrape():
    with TestClient(app) as client:
        before = client.get("/metrics").text
        client.get("/healthz")
        after = client.get("/metrics").text
        after_scrape = client.get("/metrics").text
    label = 'method="GET",route="/healthz",status="200"'
    before_count = _metric(before, "analystdesk_http_requests_total", label) if f"{label}" in before else 0
    assert _metric(after, "analystdesk_http_requests_total", label) - before_count == 1
    assert after_scrape == after


def test_success_counts_research_not_just_http_200(monkeypatch):
    from analyst_desk import stage4b3_cli

    async def good(root, thread_id, *, no_llm):
        assert no_llm is True
        return {"status": "PASS", "phase": "STAGE4B_SUPERVISOR_EVIDENCE_READY",
                "approved_plan_consumed": True, "citation_count": 23,
                "xbrl_fact_count": 6, "llm_synthesis_performed": False,
                "publication_performed": False}

    monkeypatch.setattr(stage4b3_cli, "run", good)
    label = 'outcome="success"'
    with TestClient(app) as client:
        initial = client.get("/metrics").text
        before = _metric(initial, "analystdesk_research_runs_total", label) if label in initial else 0
        response = client.post("/v1/research/stream", json={"thread_id": "a" * 32})
        assert "event: completed" in response.text
        assert "event: error" not in response.text
        after = client.get("/metrics").text
    assert _metric(after, "analystdesk_research_runs_total", label) == before + 1
    assert "analystdesk_research_duration_seconds" in after
    assert 'analystdesk_research_citations_per_run_sum' in after
    assert 'analystdesk_research_xbrl_facts_per_run_sum' in after


def test_failure_sse_is_accounted_as_failure_even_when_http_200(monkeypatch):
    from analyst_desk import stage4b3_cli

    async def broken(root, thread_id, *, no_llm):
        raise ValueError("secret-canary-credential")

    monkeypatch.setattr(stage4b3_cli, "run", broken)
    label = 'outcome="error"'
    with TestClient(app) as client:
        initial = client.get("/metrics").text
        before = _metric(initial, "analystdesk_research_runs_total", label) if label in initial else 0
        response = client.post("/v1/research/stream", json={"thread_id": "b" * 32})
        after = client.get("/metrics").text
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "event: completed" not in response.text
    assert "secret-canary-credential" not in response.text
    assert _metric(after, "analystdesk_research_runs_total", label) == before + 1


def test_untrusted_runner_result_is_not_counted_as_success(monkeypatch):
    from analyst_desk import stage4b3_cli

    async def invalid(root, thread_id, *, no_llm):
        return {"status": "PASS", "phase": "STAGE4B_SUPERVISOR_EVIDENCE_READY",
                "approved_plan_consumed": True, "citation_count": 23,
                "xbrl_fact_count": 6, "llm_synthesis_performed": True,
                "publication_performed": False}

    monkeypatch.setattr(stage4b3_cli, "run", invalid)
    with TestClient(app) as client:
        response = client.post("/v1/research/stream", json={"thread_id": "c" * 32})
    assert "event: error" in response.text
    assert "event: completed" not in response.text


def test_invalid_input_does_not_run_research(monkeypatch):
    from analyst_desk import stage4b3_cli

    async def forbidden(*args, **kwargs):
        raise AssertionError("runner must not execute")

    monkeypatch.setattr(stage4b3_cli, "run", forbidden)
    with TestClient(app) as client:
        response = client.post("/v1/research/stream", json={"thread_id": "..\\secret"})
        metrics = client.get("/metrics").text
    assert response.status_code == 422
    assert 'status="422"' in metrics

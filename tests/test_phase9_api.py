"""Offline Phase 9A adapter tests. No OpenRouter, network, MCP, or SEC calls."""
from fastapi.testclient import TestClient

from analyst_desk.phase9_api import app


def test_health_is_read_only():
    with TestClient(app) as client:
        response = client.get('/healthz')
    assert response.status_code == 200
    assert response.json() == {'status': 'UP', 'component': 'phase9a_api'}


def test_stream_rejects_invalid_thread_without_research():
    with TestClient(app) as client:
        response = client.post('/v1/research/stream', json={'thread_id': '../path'})
    assert response.status_code == 422


def test_stream_calls_existing_audited_runner_only(monkeypatch):
    # Replace the B3 module before streaming begins, and forbid real execution.
    from analyst_desk import stage4b3_cli
    calls = []
    async def stub(root, thread_id, *, no_llm):
        calls.append((thread_id, no_llm))
        return {'status': 'PASS', 'phase': 'STAGE4B_SUPERVISOR_EVIDENCE_READY',
                'approved_plan_consumed': True, 'citation_count': 9,
                'xbrl_fact_count': 3, 'llm_synthesis_performed': False,
                'publication_performed': False}
    monkeypatch.setattr(stage4b3_cli, 'run', stub)
    with TestClient(app) as client:
        response = client.post('/v1/research/stream', json={'thread_id': 'a' * 32})
    assert response.status_code == 200
    assert calls == [('a' * 32, True)]
    assert 'event: started' in response.text
    assert 'event: completed' in response.text
    assert '"publication_performed":false' in response.text
    assert 'event: error' not in response.text


def test_stream_fails_closed_without_leaking_exceptions(monkeypatch):
    from analyst_desk import stage4b3_cli
    async def stub(root, thread_id, *, no_llm):
        raise RuntimeError('secret-canary-credential')
    monkeypatch.setattr(stage4b3_cli, 'run', stub)
    with TestClient(app) as client:
        response = client.post('/v1/research/stream', json={'thread_id': 'b' * 32})
    assert response.status_code == 200
    assert 'event: error' in response.text
    assert 'RESEARCH_EXECUTION_FAILED' in response.text
    assert 'secret-canary-credential' not in response.text

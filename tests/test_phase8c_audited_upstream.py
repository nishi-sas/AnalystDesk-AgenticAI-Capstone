"""Phase 8C: explicit audited, no-upstream-LLM SEC packet; no network calls."""
from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from analyst_desk.phase7d_evaluation import (
    _load_fixed_fixture, SyntheticCanonicalMCP, ScriptedWriterClient,
    scripted_critic, scripted_rewriter,
)
from analyst_desk.phase8c_architecture import (
    ArchitectureEvalError, UPSTREAM_MODES, paired_downstream_evaluation,
    real_approved_pilot,
)
from analyst_desk.stage4c1_writer import OpenRouterReportWriter, validate_writer_input
from analyst_desk.phase8c_cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
THREAD = 'b3a5fcf8dbdb430ba814727b7c0dab14'


def audited_fixture():
    plan, evidence = _load_fixed_fixture(ROOT)
    evidence['phase'] = 'STAGE4B_SUPERVISOR_EVIDENCE_READY'
    evidence['llm_synthesis_performed'] = False
    evidence['synthesis'] = None
    validate_writer_input(plan, evidence, thread_id=THREAD, allowed=('MSFT', 'GOOGL'), budget=80000)
    return plan, evidence


def test_three_arm_downstream_accepts_audited_packet_without_fabricating_synthesis():
    plan, evidence = audited_fixture()
    frozen = deepcopy(evidence)
    record = asyncio.run(paired_downstream_evaluation(
        plan, evidence, thread_id=THREAD, allowed=('MSFT', 'GOOGL'), budget=80000,
        call=SyntheticCanonicalMCP(),
        writer_factory=lambda mode: OpenRouterReportWriter(
            SimpleNamespace(model='phase7d-scripted-model'),
            client=ScriptedWriterClient('neutral'), editorial_lessons=[]),
        critic_factory=lambda mode: scripted_critic,
        rewriter_factory=lambda mode: scripted_rewriter,
    ))
    assert record['status'] == 'PASS_PAIRED_PILOT'
    assert len(record['results']) == 3
    assert evidence == frozen
    assert all('REVENUE_GROWTH_TAG_RECONCILIATION_OPEN' in arm['hard_blockers']
               for arm in record['results'])
    assert all(arm['publication_performed'] is False for arm in record['results'])


@pytest.mark.parametrize('field,bad_value', [
    ('phase','STAGE4B_GROUNDED_SYNTHESIS_READY'),
    ('llm_synthesis_performed',True),
    ('synthesis',{'fake':'unexpected'}),
    ('publication_performed',True),
    ('semantic_entailment_checked',True),
])
def test_audited_input_strict_contract(field, bad_value):
    plan, evidence = audited_fixture()
    evidence[field] = bad_value
    with pytest.raises(Exception):
        validate_writer_input(plan, evidence, thread_id=THREAD,
                              allowed=('MSFT', 'GOOGL'), budget=80000)


def test_modes_are_explicit_and_default_cannot_fallback():
    assert UPSTREAM_MODES == ('synthesized', 'audited')


def test_cli_rejects_audited_smoke(tmp_path):
    assert cli_main(['smoke', '--project-root', str(tmp_path), '--upstream-mode', 'audited',
                     '--out', 'evidence/abc.json']) == 2
    assert not (tmp_path/'evidence'/'abc.json').exists()


def test_cli_audited_live_requires_approval(tmp_path):
    assert cli_main(['live', '--project-root', str(tmp_path), '--upstream-mode', 'audited',
                     '--thread-id', THREAD, '--out', 'evidence/abc.json']) == 2
    assert not (tmp_path/'evidence'/'abc.json').exists()


@pytest.mark.parametrize('mode', ['audited', 'synthesized'])
def test_real_pilot_selects_only_requested_upstream_mode(monkeypatch, mode):
    import analyst_desk.stage4a_config as config
    import analyst_desk.stage4b_cli as bcli
    import analyst_desk.stage4b3_cli as b3cli
    import analyst_desk.phase8c_architecture as pilot

    settings = SimpleNamespace(allowed_tickers=('MSFT', 'GOOGL'), token_budget=80000,
                               base_url='https://test.invalid', timeout_seconds=3,
                               model='fake-model')
    monkeypatch.setattr(config, 'load_planner_settings', lambda root: settings)
    monkeypatch.setattr(config, 'require_openrouter_key', lambda root: 'dummy-for-test')
    monkeypatch.setattr(bcli, 'approved_plan_from_stage4a',
                        lambda root, thread: {'companies': ['MSFT', 'GOOGL']})
    seen = []

    async def b3(root, thread, *, no_llm):
        seen.append(no_llm)
        _, evidence = audited_fixture()
        if not no_llm:
            _, evidence = _load_fixed_fixture(ROOT)
        return evidence

    class FakeOpenAI:
        def __init__(self, **kwargs): pass
        def close(self): pass

    class FakeGateway:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False

    async def paired(*args, **kwargs):
        return {'phase': 'PHASE8C_DOWNSTREAM_ARCHITECTURE_PILOT',
                'status': 'PASS_PAIRED_PILOT', 'results': []}

    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr(bcli, 'MCPResearchGateway', lambda root: FakeGateway())
    monkeypatch.setattr(b3cli, 'run', b3)
    monkeypatch.setattr(pilot, 'paired_downstream_evaluation', paired)

    record = asyncio.run(real_approved_pilot(ROOT, THREAD, upstream_mode=mode))
    assert seen == [mode == 'audited']
    assert record['shared_upstream_mode'] == mode
    assert record['shared_upstream_model_used'] is (mode == 'synthesized')
    assert record['shared_upstream_llm_requests_observed'] == (0 if mode == 'audited' else None)
    assert record['publication_performed'] is False


def test_real_pilot_rejects_unlisted_upstream_mode_without_calls(monkeypatch):
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=None))
    with pytest.raises(ArchitectureEvalError, match='UPSTREAM_MODE_INVALID'):
        asyncio.run(real_approved_pilot(ROOT, THREAD, upstream_mode='fallback'))


def test_stage4b_mode_mismatch_refused_before_downstream(monkeypatch):
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=None))
    import analyst_desk.stage4a_config as config
    import analyst_desk.stage4b_cli as bcli
    import analyst_desk.stage4b3_cli as b3cli
    settings = SimpleNamespace(allowed_tickers=('MSFT', 'GOOGL'),token_budget=80000)
    monkeypatch.setattr(config,'load_planner_settings',lambda root: settings)
    monkeypatch.setattr(bcli,'approved_plan_from_stage4a',
                        lambda root, thread: {'companies':['MSFT','GOOGL']})
    async def forged(root,thread, *, no_llm):
        _, data = _load_fixed_fixture(ROOT)  # Claim synthesized while audited requested.
        return data
    monkeypatch.setattr(b3cli, 'run', forged)
    with pytest.raises(ArchitectureEvalError, match='SHARED_UPSTREAM_MODE_CONTRACT_MISMATCH'):
        asyncio.run(real_approved_pilot(ROOT, THREAD, upstream_mode='audited'))

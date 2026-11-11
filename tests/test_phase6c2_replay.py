"""Phase 6C-2 regression: offline by default. No remote models in pytest."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from analyst_desk.phase6c_redteam import load_jsonl, RedTeamFixtureError
from analyst_desk.phase6c2_replay import (select_inputs, run_live_input_suite,
        run_graph_replay, run_external_envelope_probe, LIVE_SMOKE_ATTACK_IDS, LIVE_SMOKE_BENIGN_IDS)
from analyst_desk.phase6c2_cli import main

ROOT = Path(__file__).resolve().parents[1]
ATTACKS = load_jsonl(ROOT/'security/red_team/attacks.jsonl')
BENIGN = load_jsonl(ROOT/'security/red_team/benign.jsonl')

class FakeModels:
    def __init__(self, *, broken=None, false_block=None):
        self.broken = broken
        self.false_block = false_block
    def guardrail_kwargs(self):
        def scope(s):
            if self.broken == 'scope': raise RuntimeError('provider key=value')
            return {'in_scope': self.false_block is None or self.false_block not in s}
        def injection(s):
            if self.broken == 'injection': raise RuntimeError('model failed')
            return 0.01
        def safety(s):
            if self.broken == 'safety': raise RuntimeError('timeout')
            return {'safe': True}
        return {'scope_classifier': scope, 'injection_classifier': injection,
                'safety_classifier': safety}

def test_smoke_subset_exact_contract():
    a,b=select_inputs(ATTACKS,BENIGN,profile='smoke')
    assert [x['attack_id'] for x in a] == list(LIVE_SMOKE_ATTACK_IDS)
    assert [x['benign_id'] for x in b] == list(LIVE_SMOKE_BENIGN_IDS)

def test_full_subset_does_not_count_output_or_tool_as_live_input():
    a,b=select_inputs(ATTACKS,BENIGN,profile='full')
    assert len(a)==11 and len(b)==8
    assert all(x['probe']=='input' for x in a)

def test_invalid_profiles_and_fixture_mutations_rejected():
    with pytest.raises(ValueError): select_inputs(ATTACKS,BENIGN,profile='unsafe')
    with pytest.raises(RedTeamFixtureError): select_inputs(ATTACKS,BENIGN[:1],profile='smoke')
    with pytest.raises(RedTeamFixtureError): select_inputs(ATTACKS,BENIGN+[BENIGN[0]],profile='full')

def test_injected_mock_verdicts_pass_but_are_not_called_live():
    report=run_live_input_suite(ATTACKS,BENIGN,models=FakeModels(),profile='smoke')
    assert report['status']=='PASS'
    assert report['mode']=='INJECTED_TEST_CLASSIFIERS'
    assert report['attack_total']==6 and report['attack_blocked']==6
    assert report['benign_total']==4 and report['benign_false_blocked']==0
    assert report['model_verdicts_valid']==10
    assert 'NvApi' not in json.dumps(report)

@pytest.mark.parametrize('broken', ['scope', 'injection', 'safety'])
def test_model_failure_is_incomplete_not_security_success(broken):
    r=run_live_input_suite(ATTACKS,BENIGN,models=FakeModels(broken=broken),profile='smoke')
    assert r['status']=='INCOMPLETE'
    assert r['attack_blocked']==6  # fail closed still blocks
    assert r['model_verdicts_valid']==0
    assert 'provider key' not in json.dumps(r)

def test_false_positive_comes_through_in_score():
    r=run_live_input_suite(ATTACKS,BENIGN,models=FakeModels(false_block='Compare MSFT and GOOGL'),profile='smoke')
    assert r['status']=='ATTENTION'
    assert r['benign_false_blocked']==1

def test_incomplete_models_are_not_treated_as_optional():
    with pytest.raises(ValueError):run_live_input_suite(ATTACKS,BENIGN,models=None)
    with pytest.raises(ValueError):run_live_input_suite(ATTACKS,BENIGN,models=SimpleNamespace(guardrail_kwargs=lambda:{}))

def test_graph_full_replay_safely_stops_before_planner():
    pytest.importorskip('langgraph')
    pytest.importorskip('langgraph.checkpoint.sqlite')
    r=run_graph_replay(ATTACKS,BENIGN)
    assert r['status']=='PASS',r
    assert r['defences_on']['input_attacks']==11
    assert r['defences_on']['blocked_before_planner']==11
    assert r['defences_on']['benign_reached_review']==8
    assert r['defences_off']['real_agent_executed'] is False
    assert r['defences_off']['attack_success_measure'] is False
    assert 0 < r['defences_off']['eligible_without_input_gate'] <= 11
    assert 'sk-or-' not in json.dumps(r)

def test_cli_rejects_unsafe_destination():
    with pytest.raises(SystemExit):main(['graph','--out','../something.json'])
    with pytest.raises(SystemExit):main(['live','--out','evidence/88_wrong.json'])

def test_cli_graph_receipt_schema(tmp_path,monkeypatch,capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'security/red_team').mkdir(parents=True)
    (tmp_path/'evidence').mkdir()
    for f in ('attacks.jsonl','benign.jsonl'):
        (tmp_path/'security/red_team'/f).write_bytes((ROOT/'security/red_team'/f).read_bytes())
    monkeypatch.setattr('analyst_desk.phase6c2_cli.run_graph_replay', lambda a,b:{'phase':'MOCKED_TEST','status':'PASS','results':[{'secret':'payload'}]})
    assert main(['graph','--out','evidence/88_test.json'])==0
    assert (tmp_path/'evidence/88_test.json').exists()
    displayed=capsys.readouterr().out
    assert 'payload' not in displayed


def test_external_attack_text_is_tagged_but_not_claimed_neutralized():
    r=run_external_envelope_probe(ATTACKS)
    assert r['status']=='PASS'
    assert r['total']==10 and r['correctly_tagged_untrusted']==10
    assert r['ingestion_blocked']==0
    assert r['downstream_resilience_verified'] is False
    assert all(not x['downstream_agent_tested'] for x in r['results'])
    assert ATTACKS[0]['input'] not in json.dumps(r)


def test_external_cli_prefix_validation():
    with pytest.raises(SystemExit):main(['external','--out','evidence/89_bad.json'])

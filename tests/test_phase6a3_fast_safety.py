"""Fast safety alternative + verified Prompt Guard 2 numeric labels (no network)."""
import json
from types import SimpleNamespace
import pytest
from analyst_desk.phase6a_models import (
    openrouter_safety_verdict, _label_score, load_model_classifiers, GuardModelError)
from analyst_desk.input_guardrails import run_input_guardrails

CLEAN = 'Compare MSFT and GOOGL annual SEC filings and revenue risks.'

class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.response))])

@pytest.mark.parametrize('response,expected', [('{"safe":true}', True), ('{"safe":false}', False)])
def test_fast_safety_boolean_contract(response, expected):
    c = FakeClient(response)
    assert openrouter_safety_verdict(CLEAN, client=c)['safe'] is expected
    assert c.calls[0]['model'] == 'google/gemini-3.1-flash-lite'
    assert c.calls[0]['response_format']['type'] == 'json_object'
    assert 'untrusted_input' in c.calls[0]['messages'][1]['content']

@pytest.mark.parametrize('response', [
    'safe', '```json\n{"safe":true}\n```','{"safe":1}', '{"safe":"true"}',
    '{}', '{"safe":true,"approve":true}', 'null', '[true]', '', 'TRUE'])
def test_fast_safety_rejects_invalid_schema(response):
    with pytest.raises(GuardModelError):
        openrouter_safety_verdict(CLEAN, client=FakeClient(response))

def test_fast_safety_rejects_nonapproved_model():
    with pytest.raises(GuardModelError):
        openrouter_safety_verdict(CLEAN, client=FakeClient('{"safe":true}'), model='bad/model')

def test_numeric_label_mapping_is_not_loose():
    assert _label_score([{'label':'LABEL_1','score':.75},{'label':'LABEL_0','score':.25}]) == .75
    for labels in [
        [{'label':'LABEL_1','score':.9},{'label':'LABEL_1','score':.1}],
        [{'label':'LABEL_7','score':.9},{'label':'LABEL_0','score':.1}],
        [{'label':'LABEL_0','score':.9},{'label':'MALICIOUS','score':.1},{'label':'LABEL_1','score':0}],
    ]:
        with pytest.raises(GuardModelError): _label_score(labels)

def test_openrouter_safety_provider_uses_existing_guardrail_contract():
    models = load_model_classifiers(
        scope_client=FakeClient('{"in_scope":true}'),
        safety_client=FakeClient('{"safe":true}'),
        prompt_guard=lambda _: .02,
        safety_provider='openrouter')
    result = run_input_guardrails(CLEAN,'demo_analyst',**models.guardrail_kwargs())
    assert result.passed
    assert {x['code']:x['status'] for x in result.checks}['SAFETY_MODEL']=='PASS'
    fail_models = load_model_classifiers(
        scope_client=FakeClient('{"in_scope":true}'),
        safety_client=FakeClient('{"safe":false}'),
        prompt_guard=lambda _: .02,
        safety_provider='openrouter')
    result = run_input_guardrails(CLEAN,'demo_analyst',**fail_models.guardrail_kwargs())
    assert not result.passed and 'SAFETY_MODEL' in result.block_codes

def test_openrouter_provider_bad_response_fails_closed():
    models = load_model_classifiers(
        scope_client=FakeClient('{"in_scope":true}'),
        safety_client=FakeClient('{"safe":"maybe"}'),
        prompt_guard=lambda _: .02,
        safety_provider='openrouter')
    result = run_input_guardrails(CLEAN,'demo_analyst',**models.guardrail_kwargs())
    assert not result.passed and 'SAFETY_MODEL_ERROR' in result.block_codes

def test_default_provider_config_can_select_openrouter(monkeypatch):
    monkeypatch.setenv('ANALYSTDESK_SAFETY_PROVIDER','openrouter')
    models = load_model_classifiers(scope_client=FakeClient('{"in_scope":true}'),
                                    safety_client=FakeClient('{"safe":true}'),
                                    prompt_guard=lambda _: .01)
    assert models.safety(CLEAN)['safe']

def test_invalid_provider_fails_closed():
    with pytest.raises(GuardModelError):
        load_model_classifiers(scope_client=FakeClient('{"in_scope":true}'),
                               safety_client=FakeClient('safe'), prompt_guard=lambda _: .02,
                               safety_provider='irrelevant')

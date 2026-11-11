"""Regression tests for OpenRouter schema drift (Stage 4A live failure, 25 October)."""
import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4a_config import PlannerSettings
from analyst_desk.stage4a_graph import OpenRouterPlanner, PlanningError, offline_planner


class FakeClient:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = next(self.payloads)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])


def planner(client):
    settings = PlannerSettings('openai/gpt-5-mini', 'https://openrouter.ai/api/v1',
                               80000, ('MSFT', 'GOOGL'))
    return OpenRouterPlanner(settings, client=client)


def good_plan():
    return offline_planner('Compare MSFT and GOOGL annual results', ['MSFT', 'GOOGL'], 80000)


def test_schema_valid_first_call_avoids_additional_api_calls():
    client = FakeClient([json.dumps(good_plan())])
    result = planner(client)('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000)
    assert len(result['outline']) >= 2
    assert len(client.calls) == 1


def test_retries_short_outline_then_accepts_valid_response():
    bad = good_plan()
    bad['outline'] = ['Only one heading']
    client = FakeClient([json.dumps(bad), json.dumps(good_plan())])
    result = planner(client)('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000)
    assert result['outline'] == good_plan()['outline']
    assert len(client.calls) == 2
    followup = client.calls[1]['messages'][-1]['content']
    assert 'outline' in followup and 'ARRAY' in followup
    assert 'APPROVE' not in followup


def test_retries_string_outline_then_accepts_valid_response():
    bad = good_plan()
    bad['outline'] = 'Introduction, Scope and risks'
    client = FakeClient([json.dumps(bad), json.dumps(good_plan())])
    result = planner(client)('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000)
    assert result['outline'] == good_plan()['outline']
    assert len(client.calls) == 2


def test_retries_invalid_json_then_valid_json():
    client = FakeClient(['This is not a JSON object', json.dumps(good_plan())])
    assert planner(client)('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000)['companies'] == ['MSFT','GOOGL']
    assert len(client.calls) == 2


def test_fails_closed_after_bounded_retry():
    client = FakeClient(['{}', '{}'])
    with pytest.raises(PlanningError, match='after one schema-repair retry'):
        planner(client)('Compare MSFT and GOOGL', ['MSFT', 'GOOGL'], 80000)
    assert len(client.calls) == 2


def test_repair_does_not_accept_unauthorized_company_or_over_budget():
    rogue = good_plan()
    rogue['companies'] = ['MSFT','GOOGL','AAPL']
    overspend = good_plan()
    overspend['token_budget'] = 1_000_000
    client = FakeClient([json.dumps(rogue), json.dumps(overspend)])
    with pytest.raises(PlanningError):
        planner(client)('Compare MSFT and GOOGL', ['MSFT', 'GOOGL'], 80000)
    assert len(client.calls) == 2


def test_no_raw_invalid_model_content_ever_sent_to_repair_prompt():
    rogue_text = 'UNTRUSTED_PAYLOAD_DO_NOT_ECHO_8fae'
    invalid = json.dumps({'outline': rogue_text})
    client = FakeClient([invalid, json.dumps(good_plan())])
    planner(client)('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000)
    # Repair provides validator feedback; model content isn't replayed as new user text.
    assert rogue_text not in json.dumps(client.calls[1]['messages'])

import json
import os

import pytest

from analyst_desk.stage4a_config import Stage4AConfigError, load_planner_settings
from analyst_desk.stage4a_graph import (
    OpenRouterPlanner, PlanningError, candidate_tickers, offline_planner, validate_plan,
)
from analyst_desk.stage4a_permissions import allowed_tools, assert_tool_permission, tool_manifest, ToolPermissionError


def _root(tmp_path, *, model='openai/gpt-5-mini', url='https://openrouter.ai/api/v1', budget=80000):
    c = tmp_path / 'config'; c.mkdir()
    (c / 'models.yaml').write_text(f'supervisor_model: {model}\nbase_url: {url}\n')
    (c / 'settings.yaml').write_text(f'token_budget_per_note: {budget}\nfirst_companies: [MSFT, GOOGL]\n')
    return tmp_path


def test_load_config_and_do_not_require_key(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('ANALYSTDESK_LLM_MODEL', raising=False)
    monkeypatch.delenv('OPENROUTER_BASE_URL', raising=False)
    settings = load_planner_settings(_root(tmp_path), load_env_file=False)
    assert settings.model == 'openai/gpt-5-mini'
    assert settings.allowed_tickers == ('MSFT', 'GOOGL')
    assert settings.token_budget == 80000


@pytest.mark.parametrize('url', ['http://openrouter.ai/api/v1', 'https://example.com/api/v1',
                                 'https://openrouter.ai.evil.org/api/v1', 'https://openrouter.ai/api/v1?key=leak',
                                 'https://openrouter.ai/api/v1#fragment'])
def test_credentials_cannot_be_redirected(tmp_path, monkeypatch, url):
    monkeypatch.delenv('OPENROUTER_BASE_URL', raising=False)
    monkeypatch.delenv('ANALYSTDESK_LLM_MODEL', raising=False)
    with pytest.raises(Stage4AConfigError, match='OpenRouter URL'):
        load_planner_settings(_root(tmp_path, url=url), load_env_file=False)


def test_bad_budget_refused(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENROUTER_BASE_URL', raising=False)
    monkeypatch.delenv('ANALYSTDESK_LLM_MODEL', raising=False)
    with pytest.raises(Stage4AConfigError):
        load_planner_settings(_root(tmp_path, budget=1), load_env_file=False)


def test_request_company_detection_preserves_order():
    assert candidate_tickers('Compare Alphabet with Microsoft 2025 annual reports', ('MSFT', 'GOOGL')) == ['GOOGL', 'MSFT']
    assert candidate_tickers('Research MSFT and GOOGL 10-K risks and revenues', ('MSFT', 'GOOGL')) == ['MSFT', 'GOOGL']


@pytest.mark.parametrize('query_text', ['Tell me about Apple revenue', 'Short', 'A'*1201])
def test_unscoped_request_fails(query_text):
    with pytest.raises(PlanningError):
        candidate_tickers(query_text, ('MSFT','GOOGL'))


def test_planner_cannot_invent_extra_ticker():
    proposal = offline_planner('Compare MSFT and GOOGL', ['MSFT', 'GOOGL'], 80000)
    proposal['companies'] = ['MSFT', 'AAPL']
    with pytest.raises(PlanningError, match='unrequested'):
        validate_plan(proposal, candidates=['MSFT', 'GOOGL'], max_budget=80000)


def test_planner_cannot_exceed_budget():
    proposal = offline_planner('Compare MSFT and GOOGL', ['MSFT', 'GOOGL'], 80000)
    proposal['token_budget'] = 1000000
    with pytest.raises(PlanningError, match='budget'):
        validate_plan(proposal, candidates=['MSFT','GOOGL'], max_budget=80000)


def test_json_response_fenced_parsed_and_extra_fields_dropped():
    proposal = offline_planner('Compare MSFT and GOOGL', ['MSFT', 'GOOGL'], 80000)
    proposal['made_up_financial_fact'] = 123
    result = validate_plan('```json\n' + json.dumps(proposal) + '\n```',
                           candidates=['MSFT','GOOGL'], max_budget=80000)
    assert result['companies'] == ['MSFT', 'GOOGL']
    assert 'made_up_financial_fact' not in result


def test_malformed_plan_refused():
    with pytest.raises(PlanningError, match='invalid JSON'):
        validate_plan('{not json}', candidates=['MSFT'], max_budget=80000)


def test_planner_through_injected_api_client_no_network():
    class Message:
        content = json.dumps(offline_planner('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000))
    class Choice:
        message = Message()
    class Response:
        choices = [Choice()]
    class Completions:
        def create(self, **kwargs):
            assert kwargs['model'] == 'openai/gpt-5-mini'
            assert 'API_KEY' not in repr(kwargs)
            return Response()
    class Chat:
        completions = Completions()
    class Client:
        chat = Chat()
    from analyst_desk.stage4a_config import PlannerSettings
    runner = OpenRouterPlanner(PlannerSettings('openai/gpt-5-mini', 'https://openrouter.ai/api/v1',80000,('MSFT','GOOGL')),client=Client())
    result = runner('Compare MSFT and GOOGL', ['MSFT','GOOGL'], 80000)
    assert len(result['companies']) == 2


def test_no_agent_can_approve_itself():
    all_tools = {tool['name'] for tool in tool_manifest()}
    assert not any('approve' in name or 'sign' in name for name in all_tools)
    assert 'publish_report' not in allowed_tools('writer')
    assert 'publish_report' in allowed_tools('publisher')
    assert allowed_tools('planner') == ()


@pytest.mark.parametrize('role,tool', [('planner','search_passages'), ('filing_researcher','publish_report'),
                                      ('writer','publish_report'), ('publisher','revise_report_draft'),
                                      ('quant','create_report_draft'), ('writer','calculate_operating_margin'),
                                      ('publisher','approve_report'), ('unknown','get_passage')])
def test_disallowed_tool_rejected(role, tool):
    with pytest.raises(ToolPermissionError):
        assert_tool_permission(role,tool)


def test_known_authorized_tools():
    assert_tool_permission('filing_researcher', 'search_passages')
    assert_tool_permission('quant', 'calculate_operating_margin')
    assert_tool_permission('writer', 'create_report_draft')
    assert_tool_permission('publisher', 'publish_report')

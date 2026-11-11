"""Offline smoke regression for Phase 10 risk-only lexical routing.

Does not require Chainlit, Docker, SEC data, a hosted model or credentials.
"""
from pathlib import Path
from analyst_desk.stage4a_graph import offline_planner


def test_risk_only_request_stays_within_risk_scope():
    plan = offline_planner(
        'Compare the principal risk factors disclosed by Microsoft and Alphabet in their annual 10-K filings.',
        ['MSFT', 'GOOGL'], 80000,
    )
    assert plan['companies'] == ['MSFT', 'GOOGL']
    assert plan['token_budget'] == 80000
    assert len(plan['sub_questions']) == 3
    assert all('risk' in q.lower() for q in plan['sub_questions'])
    assert not any('revenue' in q.lower() or 'operating income' in q.lower()
                   for q in plan['sub_questions'])


def test_revenue_request_retains_existing_financial_template():
    plan = offline_planner('Compare revenue of Microsoft and Alphabet.', ['MSFT', 'GOOGL'], 80000)
    assert any('revenue and operating income' in q.lower() for q in plan['sub_questions'])


def test_mixed_request_preserves_existing_template():
    plan = offline_planner('Compare MSFT and GOOGL revenue and risk factors.', ['MSFT', 'GOOGL'], 80000)
    assert any('revenue' in q.lower() for q in plan['sub_questions'])
    assert any('risks' in q.lower() for q in plan['sub_questions'])


def test_ui_clears_sibling_actions_on_state_changes():
    ui = (Path(__file__).resolve().parents[1] / 'chainlit_app.py').read_text(encoding='utf-8')
    assert 'await previous.remove_actions()' in ui
    assert 'cl.user_session.set("plan_action_message"' in ui
    assert 'if state.get("status") != "PENDING_PLAN_REVIEW"' in ui

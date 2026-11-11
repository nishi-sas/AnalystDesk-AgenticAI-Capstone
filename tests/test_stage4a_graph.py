import json

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('langgraph.checkpoint.sqlite')

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from analyst_desk.stage4a_config import PlannerSettings
from analyst_desk.stage4a_graph import build_planning_graph, offline_planner
from analyst_desk.stage4a_cli import main

SETTINGS = PlannerSettings(model='openai/gpt-5-mini', base_url='https://openrouter.ai/api/v1',
                           token_budget=80000, allowed_tickers=('MSFT', 'GOOGL'))


def _config(name):
    return {'configurable': {'thread_id': name}}


def _pending(snapshot):
    return any(getattr(task, 'interrupts', ()) for task in (snapshot.tasks or ()))


def test_plan_pauses_and_resumes_from_sqlite_across_graph_instances(tmp_path):
    db = tmp_path / 'checkpoints.sqlite3'
    calls = []
    def plan(request,tickers,budget):
        calls.append(tickers)
        return offline_planner(request,tickers,budget)
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_planning_graph(SETTINGS, planner=plan, checkpointer=saver)
        result = graph.invoke({'request':'Compare MSFT and GOOGL annual financial reports','analyst_id':'demo_analyst'}, config=_config('t-one'))
        assert '__interrupt__' in result
        assert _pending(graph.get_state(_config('t-one')))
        assert graph.get_state(_config('t-one')).values['status'] == 'PENDING_PLAN_REVIEW'
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_planning_graph(SETTINGS, planner=plan, checkpointer=saver)
        graph.invoke(Command(resume={'action':'APPROVE'}), config=_config('t-one'))
        state = graph.get_state(_config('t-one')).values
        assert state['status'] == 'PLAN_APPROVED' and state['plan_approved']
        assert len(calls) == 1  # no second LLM call when resuming
        assert not _pending(graph.get_state(_config('t-one')))


def test_edit_requires_new_review_before_approval(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / 'edit.sqlite3')) as saver:
        graph = build_planning_graph(SETTINGS, planner=offline_planner, checkpointer=saver)
        cfg = _config('t-edit')
        graph.invoke({'request':'Compare MSFT and GOOGL annual revenues','analyst_id':'demo_analyst'}, config=cfg)
        new_plan = dict(graph.get_state(cfg).values['plan'])
        new_plan['outline'] = ['Scope', 'Cited financial analysis', 'Uncertainty']
        graph.invoke(Command(resume={'action':'EDIT','edited_plan':new_plan}), config=cfg)
        assert _pending(graph.get_state(cfg))
        assert graph.get_state(cfg).values['plan_edit_count'] == 1
        assert graph.get_state(cfg).values['plan_approved'] is False
        graph.invoke(Command(resume={'action':'APPROVE'}), config=cfg)
        assert graph.get_state(cfg).values['plan_approved'] is True


def test_reject_terminates_without_pub(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / 'reject.sqlite3')) as saver:
        graph = build_planning_graph(SETTINGS, planner=offline_planner, checkpointer=saver)
        cfg = _config('t-rej')
        graph.invoke({'request':'Analyze MSFT revenue annual filing risks','analyst_id':'demo_analyst'}, config=cfg)
        graph.invoke(Command(resume={'action':'REJECT'}), config=cfg)
        state = graph.get_state(cfg).values
        assert state['status']=='PLAN_REJECTED'
        assert state['cancelled'] is True
        assert state['plan_approved'] is False
        assert 'published_report' not in state


def test_resume_missing_thread_fails(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / 'empty.sqlite3')) as saver:
        graph = build_planning_graph(SETTINGS,planner=offline_planner,checkpointer=saver)
        assert not graph.get_state(_config('missing')).values


def test_cli_offline_start_resume_status_persists(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / 'config'; cfg.mkdir()
    (cfg/'models.yaml').write_text('supervisor_model: openai/gpt-5-mini\nbase_url: https://openrouter.ai/api/v1\n')
    (cfg/'settings.yaml').write_text('first_companies: [MSFT, GOOGL]\ntoken_budget_per_note: 80000\n')
    monkeypatch.delenv('ANALYSTDESK_LLM_MODEL', raising=False)
    monkeypatch.delenv('OPENROUTER_BASE_URL', raising=False)
    kwargs=['--project-root',str(tmp_path)]
    assert main(kwargs+['start','--offline','--thread-id','cli-one','--request', 'Compare MSFT and GOOGL annual reports'])==0
    first=json.loads(capsys.readouterr().out)
    assert first['planner_mode']=='deterministic_offline_demo'
    assert first['pending_interrupt']
    assert main(kwargs+['status','--thread-id','cli-one'])==0
    assert json.loads(capsys.readouterr().out)['status']=='PENDING_PLAN_REVIEW'
    assert main(kwargs+['resume','--thread-id','cli-one','--decision','APPROVE'])==0
    assert json.loads(capsys.readouterr().out)['status']=='PLAN_APPROVED'
    assert main(kwargs+['resume','--thread-id','cli-one','--decision','APPROVE'])==1

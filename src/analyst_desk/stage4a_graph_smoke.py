"""Real offline LangGraph + SQLite checkpoint smoke; no key, network, or SEC data required."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .stage4a_config import PlannerSettings
from .stage4a_graph import build_planning_graph, offline_planner


def main():
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    settings = PlannerSettings('openai/gpt-5-mini','https://openrouter.ai/api/v1',80000,('MSFT','GOOGL'))
    with tempfile.TemporaryDirectory(prefix='analystdesk_stage4a_') as temp:
        path = Path(temp) / 'checkpoints.sqlite3'
        cfg = {'configurable': {'thread_id': 'stage4a-smoke'}}
        with SqliteSaver.from_conn_string(str(path)) as saver:
            graph = build_planning_graph(settings, planner=offline_planner, checkpointer=saver)
            graph.invoke({'request':'Compare MSFT and GOOGL annual SEC filings and risks',
                          'analyst_id':'demo_analyst'}, config=cfg)
            initial = graph.get_state(cfg)
            assert initial.values['status'] == 'PENDING_PLAN_REVIEW'
            assert any(t.interrupts for t in initial.tasks)
        # New instance and SQLite connection: proves persisted resume, not merely in-memory state.
        with SqliteSaver.from_conn_string(str(path)) as saver:
            graph = build_planning_graph(settings, planner=offline_planner, checkpointer=saver)
            edit = dict(graph.get_state(cfg).values['plan'])
            edit['outline'] = ['Scope', 'SEC-cited evidence', 'Risks and limitations']
            graph.invoke(Command(resume={'action':'EDIT','edited_plan':edit}),config=cfg)
            edited = graph.get_state(cfg)
            assert edited.values['plan_edit_count'] == 1
            assert edited.values['status'] == 'PENDING_PLAN_REVIEW'
            assert any(t.interrupts for t in edited.tasks)
            graph.invoke(Command(resume={'action':'APPROVE'}),config=cfg)
            approved = graph.get_state(cfg).values
            assert approved['plan_approved'] is True
            assert approved['status'] == 'PLAN_APPROVED'
            assert not graph.get_state(cfg).tasks
        result = {'status':'PASS', 'transport':'real LangGraph StateGraph + SQLite checkpointer',
                  'first_interrupt':'PENDING_PLAN_REVIEW', 'edit_causes_second_review':True,
                  'resumed_after_new_database_connection':True, 'human_approve_state':'PLAN_APPROVED',
                  'financial_facts_computed':False, 'report_published':False,
                  'external_llm_called':False, 'model_credentials_required':False}
        print(json.dumps(result,indent=2))
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error_type':type(exc).__name__}))
        raise SystemExit(1)

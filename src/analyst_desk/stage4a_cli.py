"""CMD-friendly Stage 4A runner; live OpenRouter calls only with explicit commands."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .stage4a_config import PROJECT_ROOT, load_planner_settings, require_openrouter_key
from .stage4a_graph import OpenRouterPlanner, build_planning_graph, offline_planner


def _print(data: dict[str, Any]):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _summarize(graph: Any, config: dict[str, Any], thread_id: str, *, live: bool | None = None):
    snapshot = graph.get_state(config)
    state = snapshot.values or {}
    result = {'thread_id': thread_id, 'status': state.get('status', 'NOT_FOUND'),
              'plan': state.get('plan'), 'plan_approved': state.get('plan_approved', False),
              'plan_edit_count': state.get('plan_edit_count', 0),
              'pending_interrupt': bool(snapshot.tasks and any(getattr(t, 'interrupts', ()) for t in snapshot.tasks))}
    if live is not None:
        result['planner_mode'] = 'openrouter_live' if live else 'deterministic_offline_demo'
    _print(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Stage 4A: checkpointed LangGraph planning (no publishing)')
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Create a new research plan and pause for human review')
    start.add_argument('--request', required=True)
    start.add_argument('--analyst-id', default='demo_analyst')
    start.add_argument('--thread-id', default=None)
    start.add_argument('--offline', action='store_true', help='Deterministic test plan; does NOT call an LLM')
    start.add_argument('--model-guardrails', action='store_true', help='Run real scope, Prompt Guard 2 and Llama Guard 4 checks before planning')
    resume = commands.add_parser('resume', help='Resume existing plan review using the same thread ID')
    resume.add_argument('--thread-id', required=True)
    resume.add_argument('--decision', choices=['APPROVE', 'EDIT', 'REJECT'], required=True)
    resume.add_argument('--edited-plan', type=Path, default=None, help='JSON file for EDIT')
    status = commands.add_parser('status', help='Read persisted graph checkpoint')
    status.add_argument('--thread-id', required=True)
    commands.add_parser('check-llm', help='Make one small LIVE request to OpenRouter')
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve()
        settings = load_planner_settings(root)
        if args.command == 'check-llm':
            from openai import OpenAI
            client = OpenAI(api_key=require_openrouter_key(root), base_url=settings.base_url,
                            timeout=settings.timeout_seconds, max_retries=1)
            response = client.chat.completions.create(
                model=settings.model, messages=[{'role': 'user', 'content': 'Reply with exactly ANALYSTDESK_OK, no other text.'}])
            content = str(response.choices[0].message.content or '').strip()
            passed = content == 'ANALYSTDESK_OK'
            _print({'status': 'PASS' if passed else 'FAIL', 'model': settings.model,
                    'response_matches_expected': passed, 'response_excerpt': content[:80]})
            return 0 if passed else 2
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.types import Command
        db = root / 'data' / 'checkpoints' / 'stage4a.sqlite3'
        db.parent.mkdir(parents=True, exist_ok=True)
        # Context manager ensures that the SQLite connection is explicitly closed on Windows.
        with SqliteSaver.from_conn_string(str(db)) as saver:
            if args.command == 'start':
                planner = offline_planner if args.offline else OpenRouterPlanner(settings, root=root)
                thread_id = args.thread_id or uuid.uuid4().hex
                models = None
                if args.model_guardrails:
                    from .phase6a_models import load_model_classifiers
                    models = load_model_classifiers(scope_model=settings.model)
                graph = build_planning_graph(settings, planner=planner, checkpointer=saver,
                                             model_classifiers=models, require_model_checks=args.model_guardrails)
                config = {'configurable': {'thread_id': thread_id}}
                if graph.get_state(config).values:
                    raise ValueError('Thread already exists; use resume or choose a different thread ID')
                graph.invoke({'request': args.request, 'analyst_id': args.analyst_id}, config=config)
                outcome = _summarize(graph, config, thread_id, live=not args.offline)
                return 0 if outcome['status'] == 'PENDING_PLAN_REVIEW' and outcome['pending_interrupt'] else 2
            thread_id = args.thread_id
            graph = build_planning_graph(settings, planner=offline_planner, checkpointer=saver)
            config = {'configurable': {'thread_id': thread_id}}
            snap = graph.get_state(config)
            if not snap.values:
                raise ValueError('No checkpoint for this thread ID')
            if args.command == 'status':
                _summarize(graph, config, thread_id)
                return 0
            is_interrupted = any(getattr(t, 'interrupts', ()) for t in (snap.tasks or ()))
            if not is_interrupted:
                raise ValueError('No pending human review; cannot resume')
            response: dict[str, Any] = {'action': args.decision}
            if args.decision == 'EDIT':
                if args.edited_plan is None:
                    raise ValueError('EDIT requires --edited-plan path to a JSON file')
                response['edited_plan'] = json.loads(args.edited_plan.read_text(encoding='utf-8'))
            elif args.edited_plan is not None:
                raise ValueError('--edited-plan is only valid with EDIT')
            graph.invoke(Command(resume=response), config=config)
            outcome = _summarize(graph, config, thread_id)
            return 0 if outcome['status'] in {'PLAN_APPROVED', 'PLAN_REJECTED', 'PENDING_PLAN_REVIEW'} else 2
    except Exception as exc:
        # Avoid printing raw exception text: provider libraries can include request metadata.
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__,
                          'message': str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else 'See local diagnostics; credentials are not logged.'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

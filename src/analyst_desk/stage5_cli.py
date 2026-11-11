"""Phase 5 gated human review CLI. Never signs or publishes."""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT
from .stage5_hitl import build_note_gate


def _summary(graph, cfg: dict, report_id: str) -> dict:
    snapshot = graph.get_state(cfg)
    values = snapshot.values or {}
    return {'status': 'PASS', 'phase': 'PHASE5_NOTE_GATE', 'report_id': report_id,
            'gate_status': values.get('status', 'NOT_FOUND'),
            'report_sha256': values.get('report_sha256'),
            'hard_blockers': values.get('hard_blockers', []),
            'pending_interrupt': any(getattr(task, 'interrupts', ()) for task in (snapshot.tasks or ())),
            'submitted_for_review': values.get('submitted_for_review', False),
            'human_report_approved': False, 'publication_performed': False}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Phase 5: checkpointed second human gate, never signs or publishes')
    p.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    cmd = p.add_subparsers(dest='cmd', required=True)
    start = cmd.add_parser('start')
    start.add_argument('--thread-id', required=True)
    start.add_argument('--report-id', required=True)
    start.add_argument('--manifest', required=True)
    status = cmd.add_parser('status'); status.add_argument('--report-id', required=True)
    resume = cmd.add_parser('resume'); resume.add_argument('--report-id', required=True)
    resume.add_argument('--action', required=True, choices=['REQUEST_REVIEW','EDIT','REJECT'])
    resume.add_argument('--note-hash', required=True)
    a = p.parse_args(argv)
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.types import Command
        root = a.project_root.resolve()
        if not re.fullmatch(r'[0-9a-f]{32}', a.report_id):
            raise ValueError('Invalid report ID')
        os.environ.setdefault('LANGGRAPH_STRICT_MSGPACK', 'true')
        db = root/'data'/'checkpoints'/'phase5_note.sqlite3'
        db.parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(str(db)) as saver:
            g = build_note_gate(root, checkpointer=saver)
            config = {'configurable': {'thread_id': a.report_id}}
            previous = g.get_state(config)
            if a.cmd == 'start':
                if previous.values:
                    raise ValueError('Gate already initialized; cannot restart same report')
                g.invoke({'plan_thread_id': a.thread_id, 'report_id': a.report_id,
                          'manifest': a.manifest}, config=config)
            elif not previous.values:
                raise ValueError('Unknown note gate; start with the approved report first')
            elif a.cmd == 'resume':
                if not any(getattr(t, 'interrupts', ()) for t in (previous.tasks or ())):
                    raise ValueError('No pending note-review interrupt')
                g.invoke(Command(resume={'action': a.action, 'note_hash': a.note_hash}), config=config)
            result = _summary(g, config, a.report_id)
            print(json.dumps(result, indent=2))
            return 0
    except Exception as e:
        # No model output or secret contents in errors.
        print(json.dumps({'status':'ERROR','error_type':type(e).__name__,
                          'message': str(e) if isinstance(e, ValueError) else 'Gate could not complete; consult local test evidence'}))
        return 2


if __name__=='__main__':
    sys.exit(main())

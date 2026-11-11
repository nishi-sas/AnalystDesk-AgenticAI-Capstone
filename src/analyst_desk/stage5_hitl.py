"""Phase 5 — a second, checkpointed LangGraph human-control boundary.

Research has already been approved by Stage4A. Stage4C4 has registered an
unapproved draft. This gate confirms the *exact* critic-reviewed bytes before
inviting a human to request a separate cryptographically signed review.

No code in this module has access to the reviewer's signing key, and no code
in this module can approve or publish a report.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, TypedDict

from .stage4b_research import ResearchError, _tool_data
from .stage4c4_portal import PortalMCPGateway, load_reviewed_bundle

_REPORT_ID = re.compile(r'^[0-9a-f]{32}$')


class Phase5Error(ValueError):
    pass


class NoteGateState(TypedDict, total=False):
    plan_thread_id: str
    report_id: str
    manifest: str
    report_sha256: str
    revision: int
    status: str
    hard_blockers: list[str]
    submitted_for_review: bool
    human_report_approved: bool
    publication_performed: bool
    requested_action: str


def verify_exact_portal_draft(bundle: dict[str, Any], stored: dict[str, Any], *,
                              thread_id: str, report_id: str) -> dict[str, Any]:
    """Never rely only on state or the LLM's claim about portal status."""
    if not _REPORT_ID.fullmatch(report_id or ''):
        raise Phase5Error('Invalid portal report ID')
    if (bundle.get('thread_id') != thread_id or stored.get('report_id') != report_id or
            stored.get('title') != 'AnalystDesk SEC research — ' + thread_id[:12]):
        raise Phase5Error('Report is not bound to the approved research thread')
    if stored.get('status') != 'DRAFT':
        raise Phase5Error('Only an unapproved portal DRAFT may enter Phase 5 note gate')
    if (stored.get('body_sha256') != bundle.get('sha256') or
            stored.get('markdown') != bundle.get('markdown') or
            stored.get('source_ids') != bundle.get('source_ids') or
            stored.get('open_blockers') != bundle.get('blockers')):
        raise Phase5Error('Portal draft differs from the critic-reviewed evidence')
    if type(stored.get('revision')) is not int or stored['revision'] < 1:
        raise Phase5Error('Invalid portal revision')
    return {'report_sha256': bundle['sha256'], 'revision': stored['revision'],
            'hard_blockers': list(bundle['blockers'])}


async def preflight(root: Path, thread_id: str, report_id: str, manifest: str) -> dict:
    """Revalidate the approved plan, revision manifest and live MCP portal state."""
    from .stage4b_cli import approved_plan_from_stage4a
    plan = approved_plan_from_stage4a(root, thread_id)
    bundle = load_reviewed_bundle(root, thread_id, manifest,
                                  approved_companies=tuple(plan['companies']))
    async with PortalMCPGateway(root) as gateway:
        stored = _tool_data(await gateway('writer', 'get_report', {'report_id': report_id}), 'get_report')
    return verify_exact_portal_draft(bundle, stored, thread_id=thread_id, report_id=report_id)


async def request_human_review(root: Path, *, thread_id: str, report_id: str,
                               manifest: str, expected_sha256: str, expected_revision: int) -> dict:
    """Submit for human SIGNING only; this method neither signs nor publishes."""
    current = await preflight(root, thread_id, report_id, manifest)
    if (current['report_sha256'] != expected_sha256 or
            current['revision'] != expected_revision):
        raise Phase5Error('Stale note hash or revision: human action was invalidated')
    if current['hard_blockers']:
        return {'status': 'BLOCKED_UNTIL_RECONCILED', 'hard_blockers': current['hard_blockers'],
                'submitted_for_review': False}
    async with PortalMCPGateway(root) as gateway:
        response = _tool_data(await gateway('writer', 'submit_for_review', {
            'report_id': report_id, 'expected_revision': expected_revision,
        }), 'submit_for_review')
    if (response.get('status') != 'IN_REVIEW' or
            response.get('body_sha256') != expected_sha256 or
            response.get('revision') != expected_revision):
        raise Phase5Error('Signed-review handoff response mismatched the approved bytes')
    return {'status': 'AWAITING_SIGNED_HUMAN_REVIEW', 'hard_blockers': [],
            'submitted_for_review': True}


def build_note_gate(root: Path, *, checkpointer: Any):
    """Stage 5 second interrupt; run using the SAME report_id as checkpoint ID.

    The Stage4A planner owns the independent FIRST interrupt; this graph owns
    the SECOND interrupt. Both are persisted in distinct SQLite checkpoints.
    """
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    root = Path(root).resolve()

    def confirm(state: NoteGateState) -> dict:
        current = asyncio.run(preflight(root, state['plan_thread_id'], state['report_id'],
                                        state['manifest']))
        return {**current,
                'status': 'BLOCKED_UNTIL_RECONCILED' if current['hard_blockers'] else 'PENDING_NOTE_REVIEW',
                'submitted_for_review': False, 'human_report_approved': False,
                'publication_performed': False}

    def review(state: NoteGateState) -> dict:
        # Reconfirm bytes upon resume; a human cannot use a stale interrupt.
        response = interrupt({'type': 'note_review', 'report_id': state['report_id'],
                              'revision': state['revision'],
                              'note_hash': state['report_sha256'],
                              'hard_blockers': state['hard_blockers'],
                              'options': ['REQUEST_REVIEW', 'EDIT', 'REJECT'],
                              'approval_is_separate_interactive_signature': True})
        if not isinstance(response, dict):
            raise Phase5Error('Human action must be structured')
        action = response.get('action')
        if action not in {'REQUEST_REVIEW', 'EDIT', 'REJECT'}:
            raise Phase5Error('Invalid note-review action')
        if response.get('note_hash') != state['report_sha256']:
            raise Phase5Error('Human action not bound to displayed note hash')
        if action == 'EDIT':
            # Human edits MUST go through Stage4C critic + new portal revision.
            return {'status': 'EDIT_REQUIRES_CRITIC_AND_NEW_REVIEW',
                    'requested_action': action, 'human_report_approved': False}
        if action == 'REJECT':
            return {'status': 'DECLINED_BEFORE_SUBMISSION',
                    'requested_action': action, 'human_report_approved': False}
        receipt = asyncio.run(request_human_review(root,
            thread_id=state['plan_thread_id'], report_id=state['report_id'],
            manifest=state['manifest'], expected_sha256=state['report_sha256'],
            expected_revision=state['revision']))
        return {**receipt, 'requested_action': action, 'human_report_approved': False,
                'publication_performed': False}

    def route(state: NoteGateState) -> str:
        return 'stop' if state.get('hard_blockers') else 'review'

    graph = StateGraph(NoteGateState)
    graph.add_node('preflight', confirm)
    graph.add_node('note_review_interrupt', review)
    graph.add_edge(START, 'preflight')
    graph.add_conditional_edges('preflight', route, {'stop': END, 'review': 'note_review_interrupt'})
    graph.add_edge('note_review_interrupt', END)
    return graph.compile(checkpointer=checkpointer)

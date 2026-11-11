"""Phase 5 acceptance: independent second HITL, exact bytes, stale token protection."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from analyst_desk.portal_service import PortalService
from analyst_desk.stage5_hitl import Phase5Error, verify_exact_portal_draft, request_human_review

RID = 'a' * 32
THREAD = 'b' * 32
SRC = 'MSFT_2026-06-30_Item1A_00011'
MARKDOWN = '## SEC finding\n'+SRC
SHA = hashlib.sha256(MARKDOWN.encode('utf-8')).hexdigest()


def sample_packet(blockers=None):
    bundle = {'thread_id': THREAD, 'sha256': SHA, 'markdown': MARKDOWN,
              'source_ids': [SRC], 'blockers': list(blockers or [])}
    stored = {'title': 'AnalystDesk SEC research — '+THREAD[:12], 'report_id': RID,
              'status': 'DRAFT', 'revision': 1, 'body_sha256': SHA,
              'markdown': MARKDOWN, 'source_ids': [SRC], 'open_blockers': list(blockers or [])}
    return bundle, stored


def test_exact_bytes_accepted_for_second_gate():
    b,r = sample_packet()
    assert verify_exact_portal_draft(b,r,thread_id=THREAD,report_id=RID) == {
        'report_sha256': SHA,'revision':1,'hard_blockers':[]}


@pytest.mark.parametrize('change', [
    {'status':'APPROVED'}, {'title':'Another analyst note'},
    {'report_id':'c'*32}, {'body_sha256':'0'*64},
    {'markdown':'changed'}, {'source_ids':[]},
    {'open_blockers':['another blocker']}, {'revision':True},
    {'revision':0},
])
def test_changed_portal_packet_refused(change):
    b,r=sample_packet();r.update(change)
    with pytest.raises(Phase5Error):
        verify_exact_portal_draft(b,r,thread_id=THREAD,report_id=RID)


def test_wrong_thread_and_report_id_fail_closed():
    b,r = sample_packet()
    with pytest.raises(Phase5Error):
        verify_exact_portal_draft(b,r,thread_id='c'*32,report_id=RID)
    with pytest.raises(Phase5Error):
        verify_exact_portal_draft(b,r,thread_id=THREAD,report_id='../etc')


def test_blocked_packet_preserves_blocker_without_human_interrupt():
    b,r = sample_packet(['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'])
    o=verify_exact_portal_draft(b,r,thread_id=THREAD,report_id=RID)
    assert o['hard_blockers'] == ['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN']


def test_request_review_fails_closed_on_open_blocker(monkeypatch, tmp_path):
    import analyst_desk.stage5_hitl as m
    async def stub(*args, **kwargs):
        return {'report_sha256':SHA,'revision':1,'hard_blockers':['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN']}
    monkeypatch.setattr(m, 'preflight', stub)
    r = asyncio.run(request_human_review(tmp_path,thread_id=THREAD,report_id=RID,
              manifest='evidence/manifest.json', expected_sha256=SHA,expected_revision=1))
    assert r['status']=='BLOCKED_UNTIL_RECONCILED' and not r['submitted_for_review']


@pytest.mark.parametrize('expected_sha,rev',[('f'*64,1),(SHA,2)])
def test_stale_note_action_prevents_mcp_submission(monkeypatch, tmp_path, expected_sha, rev):
    import analyst_desk.stage5_hitl as m
    async def stub(*args, **kwargs):
        return {'report_sha256':SHA,'revision':1,'hard_blockers':[]}
    monkeypatch.setattr(m,'preflight',stub)
    with pytest.raises(Phase5Error,match='Stale'):
        asyncio.run(request_human_review(tmp_path,thread_id=THREAD,report_id=RID,
               manifest='evidence/manifest.json',expected_sha256=expected_sha,
               expected_revision=rev))


def test_signed_human_approval_then_edit_rejects_old_signature_and_hash(tmp_path):
    """Acceptance 5.2. Real Ed25519 signatures in ISOLATED test SQLite only."""
    key=Ed25519PrivateKey.generate()
    pub=tmp_path/'reviewer.pem'
    pub.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    portal=PortalService(tmp_path/'isolated.sqlite3',pub)
    create=portal.create_report_draft('Isolated human-control test', MARKDOWN, [SRC])
    assert create['ok']
    rid=create['data']['report_id'];old_sha=create['data']['body_sha256']
    assert portal.publish_report(rid,old_sha)['error_code']=='APPROVAL_REQUIRED'
    assert portal.submit_for_review(rid,1)['ok']
    signed=portal.record_signed_review(rid, 'Test-only reviewer', 'APPROVE', key)
    assert signed['ok'] and signed['data']['body_sha256']==old_sha
    # Approval existed for v1. Edits replace current body/revision; signature must not transfer.
    revised=portal.revise_report_draft(rid,1,MARKDOWN+'\n## Human-edited finding',[SRC])
    assert revised['ok'] and revised['data']['revision']==2
    new_sha=revised['data']['body_sha256']
    assert new_sha!=old_sha and revised['data']['status']=='DRAFT'
    assert portal.publish_report(rid,old_sha)['ok'] is False
    assert portal.publish_report(rid,new_sha)['error_code']=='APPROVAL_REQUIRED'
    assert portal.submit_for_review(rid,1)['error_code']=='VERSION_CONFLICT'
    assert portal.get_report(rid)['data']['publication'] is None


def test_signed_human_rejection_never_publishes(tmp_path):
    key=Ed25519PrivateKey.generate()
    pub=tmp_path/'reviewer.pem'
    pub.write_bytes(key.public_key().public_bytes(encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    portal=PortalService(tmp_path/'isolated.sqlite3',pub)
    d=portal.create_report_draft('Isolated rejected test',MARKDOWN,[SRC])['data']
    assert portal.submit_for_review(d['report_id'],1)['ok']
    assert portal.record_signed_review(d['report_id'],'Test reviewer','REJECT',key)['ok']
    assert portal.publish_report(d['report_id'],d['body_sha256'])['ok'] is False


def test_blockers_reject_review_in_portal_and_do_not_sign(tmp_path):
    portal=PortalService(tmp_path/'isolated.sqlite3',tmp_path/'missing.pem')
    d=portal.create_report_draft('Blocked SEC test',MARKDOWN,[SRC],
           ['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'])['data']
    refused=portal.submit_for_review(d['report_id'],1)
    assert refused['error_code']=='OPEN_BLOCKERS'
    assert portal.get_report(d['report_id'])['data']['status']=='DRAFT'


# Requires installed LangGraph on user's Windows workstation.
# Graph tests reside in this same module but skip selectively in local minimal CI.
@pytest.mark.parametrize('action,expected',[('EDIT','EDIT_REQUIRES_CRITIC_AND_NEW_REVIEW'),
                                             ('REJECT','DECLINED_BEFORE_SUBMISSION')])
def test_checkpointed_second_interrupt_edit_reject(tmp_path,monkeypatch,action,expected):
    pytest.importorskip('langgraph')
    pytest.importorskip('langgraph.checkpoint.sqlite')
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    import analyst_desk.stage5_hitl as m
    async def stub(*args,**kwargs):
        return {'report_sha256':SHA,'revision':1,'hard_blockers':[]}
    monkeypatch.setattr(m,'preflight',stub)
    cfg={'configurable':{'thread_id':RID}}
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite3')) as cp:
        g=m.build_note_gate(tmp_path,checkpointer=cp)
        r=g.invoke({'plan_thread_id':THREAD,'report_id':RID,'manifest':'evidence/test.json'},config=cfg)
        assert '__interrupt__' in r
        g.invoke(Command(resume={'action':action,'note_hash':SHA}),config=cfg)
        s=g.get_state(cfg)
        assert s.values['status']==expected and not s.values['human_report_approved']
        assert not any(t.interrupts for t in (s.tasks or []))


def test_checkpointed_second_gate_refuses_blocked_packet(tmp_path, monkeypatch):
    pytest.importorskip('langgraph')
    pytest.importorskip('langgraph.checkpoint.sqlite')
    from langgraph.checkpoint.sqlite import SqliteSaver
    import analyst_desk.stage5_hitl as m
    async def blocked(*a,**k):
        return {'report_sha256':SHA,'revision':1,
                'hard_blockers':['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN']}
    monkeypatch.setattr(m,'preflight',blocked)
    cfg={'configurable':{'thread_id':RID}}
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite3')) as cp:
        g=m.build_note_gate(tmp_path,checkpointer=cp)
        g.invoke({'plan_thread_id':THREAD,'report_id':RID,'manifest':'evidence/test.json'},config=cfg)
        snap=g.get_state(cfg)
        assert snap.values['status']=='BLOCKED_UNTIL_RECONCILED'
        assert not any(t.interrupts for t in (snap.tasks or []))


def test_checkpointed_second_interrupt_resume_requests_only_signed_review(tmp_path,monkeypatch):
    pytest.importorskip('langgraph')
    pytest.importorskip('langgraph.checkpoint.sqlite')
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    import analyst_desk.stage5_hitl as m
    async def stub(*a,**kw):
        return {'report_sha256':SHA,'revision':1,'hard_blockers':[]}
    async def submit(*a,**kw):
        return {'status':'AWAITING_SIGNED_HUMAN_REVIEW','hard_blockers':[],
                'submitted_for_review':True}
    monkeypatch.setattr(m,'preflight',stub)
    monkeypatch.setattr(m,'request_human_review',submit)
    cfg={'configurable':{'thread_id':RID}}
    db=str(tmp_path/'persisted.sqlite3')
    with SqliteSaver.from_conn_string(db) as cp:
        g=m.build_note_gate(tmp_path,checkpointer=cp)
        g.invoke({'plan_thread_id':THREAD,'report_id':RID,'manifest':'evidence/test.json'},config=cfg)
        assert any(t.interrupts for t in g.get_state(cfg).tasks)
    with SqliteSaver.from_conn_string(db) as cp:
        g=m.build_note_gate(tmp_path,checkpointer=cp)
        g.invoke(Command(resume={'action':'REQUEST_REVIEW','note_hash':SHA}),config=cfg)
        state=g.get_state(cfg).values
        assert state['status']=='AWAITING_SIGNED_HUMAN_REVIEW'
        assert state['submitted_for_review']
        assert not state['human_report_approved']
        assert not state['publication_performed']


def test_stale_displayed_hash_rejected_by_graph(tmp_path,monkeypatch):
    pytest.importorskip('langgraph')
    pytest.importorskip('langgraph.checkpoint.sqlite')
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    import analyst_desk.stage5_hitl as m
    async def stub(*a,**kw):
        return {'report_sha256':SHA,'revision':1,'hard_blockers':[]}
    monkeypatch.setattr(m,'preflight',stub)
    cfg={'configurable':{'thread_id':RID}}
    with SqliteSaver.from_conn_string(str(tmp_path/'persisted.sqlite3')) as cp:
        g=m.build_note_gate(tmp_path,checkpointer=cp)
        g.invoke({'plan_thread_id':THREAD,'report_id':RID,'manifest':'evidence/test.json'},config=cfg)
        with pytest.raises(Phase5Error,match='not bound'):
            g.invoke(Command(resume={'action':'REQUEST_REVIEW','note_hash':'f'*64}),config=cfg)

@pytest.mark.asyncio
async def test_original_phase5_acceptance_stale_approval_rejected_by_publish_mcp(tmp_path):
    """5.2 exact acceptance: sign v1, EDIT to v2, stale signature rejected by MCP."""
    pytest.importorskip('fastmcp')
    from analyst_desk.stage4c4_portal import PortalMCPGateway
    key=Ed25519PrivateKey.generate()
    pub=tmp_path/'data'/'research_portal'/'reviewer_public.pem'
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    svc=PortalService(pub.parent/'portal.sqlite3',pub)
    d=svc.create_report_draft('Isolated MCP test',MARKDOWN,[SRC])['data']
    rid=d['report_id']; sha_v1=d['body_sha256']
    assert svc.submit_for_review(rid,1)['ok']
    signed=svc.record_signed_review(rid,'Isolated test reviewer','APPROVE',key)
    assert signed['ok'] and signed['data']['revision']==1
    updated=svc.revise_report_draft(rid,1,MARKDOWN+'\nUpdate from reviewer',[SRC])
    assert updated['ok'] and updated['data']['revision']==2
    sha_v2=updated['data']['body_sha256']
    async with PortalMCPGateway(tmp_path) as portal:
        old=await portal('publisher','publish_report',{
            'report_id':rid,'expected_sha256':sha_v1})
        new=await portal('publisher','publish_report',{
            'report_id':rid,'expected_sha256':sha_v2})
    assert old['ok'] is False and new['ok'] is False
    assert svc.get_report(rid)['data']['status']=='DRAFT'
    assert svc.get_report(rid)['data']['publication'] is None

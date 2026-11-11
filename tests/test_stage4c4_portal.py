"""Stage 4C-4 portal handoff security and integration acceptance contracts."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from analyst_desk.portal_service import PortalService
from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4c4_portal import load_reviewed_bundle,register_reviewed_draft
from analyst_desk.stage4c4_cli import execute

THREAD='b3a5fcf8dbdb430ba814727b7c0dab14'
MS='MSFT_2026-06-30_Item1A_00011'
GO='GOOGL_2025-12-31_Item1A_00022'
FACT='CIK0000789019|0001193125-26-323660|us-gaap:OperatingIncomeLoss|2025-07-01:2026-06-30|USD'
BLOCK='REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'


def make_bundle(root, *, blockers=None, verdict='SUPPORTED'):
    root=Path(root);(root/'evidence').mkdir(exist_ok=True)
    blockers=[BLOCK] if blockers is None else blockers
    md=('**STATUS: UNREVIEWED DRAFT — NOT APPROVED FOR PUBLICATION**\n'
        f'Microsoft evidence `{MS}` and Alphabet evidence `{GO}`.\n'
        f'Financial source `{FACT}`.\n')
    sha=hashlib.sha256(md.encode()).hexdigest()
    findings=[{'claim_id':k,'verdict':verdict,'reason':'Source-backed provisional narrative',
               'citations':[MS,GO],'human_verified':False}
              for k in ['cyber_privacy','ai_ip','competition_regulation','service_infrastructure','executive_summary']]
    review={'status':'PASS','phase':'STAGE4C_CRITIC_REPORT_READY','source_thread_id':THREAD,
            'draft_sha256':sha,'critic_review_performed':True,
            'human_report_approved':False,'report_submitted_for_review':False,
            'publication_performed':False,'semantic_entailment_checked':False,
            'model_semantic_assessment_performed':True,'claim_count':5,'findings':findings,
            'hard_blockers':blockers,'review_disposition':'REQUIRES_HUMAN_REVIEW'}
    (root/'evidence'/'test_stage4c4_v0_draft.md').write_text(md,encoding='utf-8')
    (root/'evidence'/'test_stage4c4_v0_review.json').write_text(json.dumps(review),encoding='utf-8')
    version={'version':0,'draft_sha256':sha,'draft_path':'evidence/test_stage4c4_v0_draft.md',
             'review_path':'evidence/test_stage4c4_v0_review.json','hard_blockers':blockers,
             'review_disposition':'REQUIRES_HUMAN_REVIEW'}
    m={'status':'PASS','phase':'STAGE4C_REVIEW_BLOCKED' if blockers else 'STAGE4C_READY_FOR_HUMAN_REVIEW',
       'thread_id':THREAD,'revision_count':0,'max_revisions':2,'revision_actions':[],
       'versions':[version],'hard_blockers':blockers,'human_report_approved':False,
       'report_submitted_for_review':False,'publication_performed':False}
    (root/'evidence'/'test_stage4c4_manifest.json').write_text(json.dumps(m),encoding='utf-8')
    return m, review


def load(root):
    return load_reviewed_bundle(root,THREAD,'evidence/test_stage4c4_manifest.json',
                                approved_companies=('MSFT','GOOGL'))


def test_bundled_reviewed_report_binds_exact_hash_and_blocker(tmp_path):
    make_bundle(tmp_path)
    data=load(tmp_path)
    assert data['blockers']==[BLOCK] and len(data['source_ids'])==3
    assert data['source_ids']==[MS,GO,FACT]


def test_draft_tampering_refused(tmp_path):
    make_bundle(tmp_path)
    with (tmp_path/'evidence'/'test_stage4c4_v0_draft.md').open('a',encoding='utf-8') as file: file.write('changed')
    with pytest.raises(ResearchError,match='digest'):load(tmp_path)


def test_manifest_bad_thread_refused(tmp_path):
    make_bundle(tmp_path)
    with pytest.raises(ResearchError,match='unbound'):load_reviewed_bundle(
        tmp_path,'0'*32,'evidence/test_stage4c4_manifest.json',approved_companies=('MSFT','GOOGL'))


def test_review_approval_forgery_refused(tmp_path):
    make_bundle(tmp_path)
    path=tmp_path/'evidence'/'test_stage4c4_v0_review.json'; data=json.loads(path.read_text())
    data['human_report_approved']=True;path.write_text(json.dumps(data))
    with pytest.raises(ResearchError,match='falsely approved'):load(tmp_path)


def test_source_scope_refused(tmp_path):
    make_bundle(tmp_path)
    with pytest.raises(ResearchError,match='outside approved company scope'):
        load_reviewed_bundle(tmp_path,THREAD,'evidence/test_stage4c4_manifest.json',
                             approved_companies=('GOOGL',))


def test_blocker_removed_in_manifest_refused(tmp_path):
    make_bundle(tmp_path)
    path=tmp_path/'evidence'/'test_stage4c4_manifest.json';m=json.loads(path.read_text())
    m['hard_blockers']=[];path.write_text(json.dumps(m))
    with pytest.raises(ResearchError,match='blocker mismatch'):load(tmp_path)


def test_malformed_path_refused(tmp_path):
    make_bundle(tmp_path)
    with pytest.raises(ResearchError):load_reviewed_bundle(
        tmp_path,THREAD,'evidence/../.env',approved_companies=('MSFT','GOOGL'))


@pytest.mark.asyncio
async def test_portal_mcp_draft_blocked_and_no_auto_submission(tmp_path):
    make_bundle(tmp_path)
    portal=PortalService(tmp_path/'portal.sqlite3',tmp_path/'public.pem')
    calls=[]
    async def call(role,name,args):
        calls.append((role,name))
        return getattr(portal,name)(**args)
    r=await register_reviewed_draft(load(tmp_path),call)
    assert r['phase']=='STAGE4C_PORTAL_DRAFT_BLOCKED'
    assert calls==[('writer','create_report_draft'),('writer','get_report')]
    assert portal.get_report(r['report_id'])['data']['open_blockers']==[BLOCK]
    rejected=portal.submit_for_review(r['report_id'],1)
    assert rejected['error_code']=='OPEN_BLOCKERS'
    assert portal.publish_report(r['report_id'],r['draft_sha256'])['error_code']=='APPROVAL_REQUIRED'


@pytest.mark.asyncio
async def test_explicit_request_review_refuses_blocked_draft(tmp_path,monkeypatch):
    make_bundle(tmp_path)
    portal=PortalService(tmp_path/'portal.sqlite3',tmp_path/'public.pem')
    async def call(role,name,args):return getattr(portal,name)(**args)
    registered=await register_reviewed_draft(load(tmp_path),call)
    class FakeGateway:
        def __init__(self,root):pass
        async def __aenter__(self):return call
        async def __aexit__(self,*args):pass
    from analyst_desk import stage4c4_cli
    monkeypatch.setattr(stage4c4_cli,'PortalMCPGateway',FakeGateway)
    args=SimpleNamespace(command='submit',report_id=registered['report_id'])
    result=await execute(tmp_path,args)
    assert result['phase']=='STAGE4C_PORTAL_SUBMISSION_BLOCKED'
    assert portal.get_report(registered['report_id'])['data']['status']=='DRAFT'


@pytest.mark.asyncio
async def test_separate_signature_required_for_ready_report(tmp_path):
    make_bundle(tmp_path,blockers=[])
    portal=PortalService(tmp_path/'portal.sqlite3',tmp_path/'public.pem')
    async def call(role,name,args):return getattr(portal,name)(**args)
    registered=await register_reviewed_draft(load(tmp_path),call)
    assert registered['phase']=='STAGE4C_PORTAL_DRAFT_READY'
    rid=registered['report_id'];sha=registered['draft_sha256']
    assert portal.publish_report(rid,sha)['error_code']=='APPROVAL_REQUIRED'
    assert portal.submit_for_review(rid,1)['ok']
    assert portal.publish_report(rid,sha)['error_code']=='APPROVAL_REQUIRED'
    key=Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    tmp=(tmp_path/'public.pem')
    tmp.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,format=serialization.PublicFormat.SubjectPublicKeyInfo))
    assert portal.record_signed_review(rid,'External reviewer','APPROVE',key)['ok']
    assert portal.publish_report(rid,sha)['ok']
    assert portal.get_report(rid)['data']['status']=='PUBLISHED'


@pytest.mark.asyncio
async def test_unauthorized_publisher_role_cannot_create(tmp_path):
    from analyst_desk.stage4a_permissions import assert_tool_permission,ToolPermissionError
    with pytest.raises(ToolPermissionError):assert_tool_permission('publisher','create_report_draft')
    with pytest.raises(ToolPermissionError):assert_tool_permission('writer','publish_report')


def test_missing_fiscal_numeric_provenance_refused(tmp_path):
    make_bundle(tmp_path)
    doc=tmp_path/'evidence'/'test_stage4c4_v0_draft.md'
    # This fixture contains a Unicode em dash. On Windows, default code-page
    # decoding may silently mojibake it, causing a false digest mismatch before
    # the missing-SEC-fact contract can be tested. Use UTF-8 on both sides.
    changed=doc.read_text(encoding='utf-8').replace(
        f'Financial source `{FACT}`.', 'Financial source was not documented.')
    assert f'`{FACT}`' not in changed
    sha=hashlib.sha256(changed.encode('utf-8')).hexdigest()
    doc.write_text(changed, encoding='utf-8')
    rp=tmp_path/'evidence'/'test_stage4c4_v0_review.json';rev=json.loads(rp.read_text());rev['draft_sha256']=sha;rp.write_text(json.dumps(rev))
    mp=tmp_path/'evidence'/'test_stage4c4_manifest.json';m=json.loads(mp.read_text());m['versions'][0]['draft_sha256']=sha;mp.write_text(json.dumps(m))
    with pytest.raises(ResearchError,match='SEC facts'):load(tmp_path)

@pytest.mark.asyncio
async def test_real_fastmcp_portal_gateway_draft_handoff(tmp_path):
    pytest.importorskip('fastmcp')
    from analyst_desk.stage4c4_portal import PortalMCPGateway
    make_bundle(tmp_path)
    async with PortalMCPGateway(tmp_path) as gateway:
        result=await register_reviewed_draft(load(tmp_path),gateway)
        assert result['phase']=='STAGE4C_PORTAL_DRAFT_BLOCKED'
        assert result['source_count']==3
        record=await gateway('writer','get_report',{'report_id':result['report_id']})
        assert record['ok'] and record['data']['open_blockers']==[BLOCK]

"""Stage 4C-3: evidence-preserving bounded revision and proper stop conditions."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4c3_cli import output_prefix
from analyst_desk.stage4c3_revision import (
    MAX_REVISIONS, _targets, targeted_revision, run_revision_loop, OpenRouterTargetedRewriter,
)
from test_stage4c1_writer import THREAD, packet_fixture, valid_summary
from test_stage4c2_critic import FakeMCP
from analyst_desk.stage4c1_writer import validate_executive_summary

ALLOW=('MSFT','GOOGL')
BUDGET=80000


def summary_writer(validated):
    data=json.loads(valid_summary(validated['plan'], {'risk_evidence_citations':{
        theme:{ticker:[entry['passage_id'] for entry in rows] for ticker,rows in entries.items()}
               for theme,entries in validated['risk_packet']['risk_evidence'].items()}}))
    return validate_executive_summary(json.dumps(data),validated)


def critic(verdict='SUPPORTED', target=None):
    def model(claim_id,text,ids,source_packet):
        return {'claim_id':claim_id,'verdict': verdict if target is None or claim_id==target else 'SUPPORTED',
                'reason':'The passages provide an adequate basis for the cited risk description',
                'citations':ids,'human_verified':False}
    return model


@pytest.mark.asyncio
async def test_offline_zero_revision_not_semantically_reviewed():
    plan,evidence=packet_fixture(offline=True)
    result=await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                   call=FakeMCP(),writer=None,critic=None)
    assert result['phase']=='STAGE4C_SEMANTIC_REVIEW_PENDING'
    assert result['revision_count']==0 and len(result['versions'])==1
    assert result['human_report_approved'] is False and result['publication_performed'] is False


@pytest.mark.asyncio
async def test_all_supported_zero_revisions_unresolved_xbrl_blocker():
    plan,evidence=packet_fixture()
    result=await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                   call=FakeMCP(),writer=summary_writer,critic=critic())
    assert result['phase']=='STAGE4C_REVIEW_BLOCKED'
    assert result['revision_count']==0
    assert 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN' in result['hard_blockers']
    assert len(result['versions'])==1


@pytest.mark.asyncio
async def test_all_supported_zero_revisions_human_review_only_without_blockers():
    plan,evidence=packet_fixture()
    evidence['warnings']=[w for w in evidence['warnings'] if not w.endswith(':REVENUE_TAG_RECONCILIATION_REQUIRED')]
    # Cannot remove the warning without changing a validated XBRL classification.
    with pytest.raises(ResearchError):
        await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                call=FakeMCP(),writer=summary_writer,critic=critic())


@pytest.mark.asyncio
async def test_unsupported_risk_rewrite_two_round_limit_enforced():
    plan,evidence=packet_fixture()
    count=[]
    def rewriter(**kwargs):
        count.append(kwargs['claim_id'])
        old=kwargs['previous_text']
        return {'text':old+' Additional source-supported context.', 'citations':kwargs['allowed_citations']}
    result=await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                   call=FakeMCP(),writer=summary_writer,
                                   critic=critic('UNSUPPORTED','cyber_privacy'),rewriter=rewriter)
    assert result['phase']=='STAGE4C_REVISION_LIMIT_REACHED'
    assert result['revision_count']==2 and len(count)==2
    assert [v['version'] for v in result['versions']]==[0,1,2]
    assert len(set(v['draft_sha256'] for v in result['versions']))==3
    assert all(v['draft']['publication_performed'] is False for v in result['versions'])


@pytest.mark.asyncio
async def test_unsupported_revisions_can_converge_to_eligible_for_human_review_but_not_publication():
    plan,evidence=packet_fixture()
    calls=[0]
    def model(claim_id,text,ids,sp):
        if claim_id=='ai_ip':
            calls[0]+=1
            outcome='UNSUPPORTED' if calls[0]==1 else 'SUPPORTED'
        else: outcome='SUPPORTED'
        return {'claim_id':claim_id,'verdict':outcome,
                'reason':'Passages are relevant but the phrasing may overreach',
                'citations':ids}
    def rewriter(**kwargs):
        return {'text':kwargs['previous_text']+' The evidence remains preliminary.', 'citations':kwargs['allowed_citations']}
    result=await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                   call=FakeMCP(),writer=summary_writer,critic=model,rewriter=rewriter)
    assert result['revision_count']==1 and len(result['versions'])==2
    assert result['revision_actions'][0]['revised_claim_ids']==['ai_ip']
    assert result['phase']=='STAGE4C_REVIEW_BLOCKED'  # XBRL blocker preserved.
    assert result['human_report_approved'] is False


@pytest.mark.asyncio
async def test_no_rewriter_never_loops_indefinitely():
    plan,evidence=packet_fixture()
    res=await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                call=FakeMCP(),writer=summary_writer,critic=critic('UNSUPPORTED','cyber_privacy'))
    assert res['revision_count']==0 and res['phase']=='STAGE4C_REVIEW_BLOCKED'


@pytest.mark.asyncio
async def test_invalid_budget_revisions_rejected_before_tool_calls():
    plan,evidence=packet_fixture()
    with pytest.raises(ResearchError):
        await run_revision_loop(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                call=FakeMCP(),max_revisions=3)


def test_unbound_review_sha_rejected():
    draft={'thread_id':THREAD, 'draft_markdown':'hello'}
    review={'status':'PASS','phase':'STAGE4C_CRITIC_REPORT_READY','source_thread_id':THREAD,
            'draft_sha256':'0'*64,'critic_review_performed':True,
            'human_report_approved':False,'report_submitted_for_review':False,
            'publication_performed':False,'semantic_entailment_checked':False,
            'findings':[],'claim_count':0,'hard_blockers':[]}
    with pytest.raises(ResearchError):_targets(review,expected_ids=set(),draft=draft)


@pytest.mark.parametrize('path',[ '../.env','evidence/../.env','results/foo',
                                 'evidence/test.txt','evidence/ab','evidence/foo/bar',
                                 'evidence/x;del', '/evidence/safe'])
def test_path_restrictions(path,tmp_path):
    with pytest.raises(ResearchError):output_prefix(tmp_path,path)


def test_good_path_restrictions(tmp_path):
    assert output_prefix(tmp_path,'evidence/55_stage4c3_test').parent.name=='evidence'


@pytest.mark.asyncio
async def test_revision_proposal_cannot_replace_citations():
    plan,evidence=packet_fixture()
    from analyst_desk.stage4c1_writer import produce_draft
    from analyst_desk.stage4c2_critic import review_report
    d=produce_draft(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,writer=summary_writer)
    rev=await review_report(plan,evidence,d,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                            call=FakeMCP(),model=critic('UNSUPPORTED','ai_ip'))
    def rewriter(**kwargs):return {'text':kwargs['previous_text']+' Different phrasing.', 'citations':['FAKE_2020-01-01_Item1A_00001']}
    with pytest.raises(ResearchError):
        await targeted_revision(plan,evidence,d,rev,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                call=FakeMCP(),rewriter=rewriter)


@pytest.mark.asyncio
async def test_revision_does_not_change_metric_or_warning():
    plan,evidence=packet_fixture()
    initial=deepcopy(evidence)
    from analyst_desk.stage4c1_writer import produce_draft
    from analyst_desk.stage4c2_critic import review_report
    d=produce_draft(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,writer=summary_writer)
    rev=await review_report(plan,evidence,d,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                            call=FakeMCP(),model=critic('UNSUPPORTED','ai_ip'))
    def rewriter(**kwargs):return {'text':kwargs['previous_text']+' Descriptions require further review.',
                                  'citations':kwargs['allowed_citations']}
    new_evidence,new_draft,mods=await targeted_revision(plan,evidence,d,rev,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                                           call=FakeMCP(),rewriter=rewriter)
    assert new_evidence['financial_comparability']==initial['financial_comparability']
    assert new_evidence['warnings']==initial['warnings']
    assert new_evidence['risk_evidence_citations']==initial['risk_evidence_citations']
    assert new_draft['publication_performed'] is False and mods==['ai_ip']
    assert evidence==initial


@pytest.mark.asyncio
async def test_rewriter_cannot_output_self_approval():
    plan,evidence=packet_fixture()
    from analyst_desk.stage4c1_writer import produce_draft
    from analyst_desk.stage4c2_critic import review_report
    d=produce_draft(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,writer=summary_writer)
    rev=await review_report(plan,evidence,d,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                            call=FakeMCP(),model=critic('UNSUPPORTED','ai_ip'))
    def rewriter(**kwargs):return {'text':kwargs['previous_text']+' Corrected text.',
                                  'citations':kwargs['allowed_citations'],'approved':True}
    with pytest.raises(ResearchError):
        await targeted_revision(plan,evidence,d,rev,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                call=FakeMCP(),rewriter=rewriter)


@pytest.mark.asyncio
async def test_real_langgraph_revision_graph_zero_round_blocked():
    pytest.importorskip('langgraph')
    from analyst_desk.stage4c3_revision import run_revision_graph
    plan,evidence=packet_fixture()
    result=await run_revision_graph(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                    call=FakeMCP(),writer=summary_writer,critic=critic())
    assert result['phase']=='STAGE4C_REVIEW_BLOCKED'
    assert result['revision_count']==0 and len(result['versions'])==1


@pytest.mark.asyncio
async def test_real_langgraph_revision_graph_exact_two_round_limit():
    pytest.importorskip('langgraph')
    from analyst_desk.stage4c3_revision import run_revision_graph
    plan,evidence=packet_fixture()
    def rewriter(**kwargs):
        return {'text':kwargs['previous_text']+' This narrative needs an independent human review.',
                'citations':kwargs['allowed_citations']}
    result=await run_revision_graph(plan,evidence,thread_id=THREAD,allowed=ALLOW,budget=BUDGET,
                                    call=FakeMCP(),writer=summary_writer,
                                    critic=critic('UNSUPPORTED','cyber_privacy'),rewriter=rewriter)
    assert result['phase']=='STAGE4C_REVISION_LIMIT_REACHED'
    assert result['revision_count']==2 and len(result['versions'])==3
    assert all(v['draft']['human_report_approved'] is False for v in result['versions'])

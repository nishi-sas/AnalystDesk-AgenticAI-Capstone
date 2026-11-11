"""Phase 7D: honest scripted A/B experiment and fail-closed output controls."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from analyst_desk.phase7d_evaluation import (
    CASES, FIXTURE_SHA256, ExperimentError, GOOD_SUMMARY, OVERCLAIM_SUMMARY,
    _advice, _load_fixed_fixture, _source_fingerprint, evaluate, run_condition,
    ScriptedWriterClient, SyntheticCanonicalMCP,
)
from analyst_desk.phase7d_cli import main
from analyst_desk.phase7a_reflexion import ReflexionError


@pytest.fixture
def fixture_root(tmp_path):
    src=Path(__file__).resolve().parents[1]/'security'/'phase7d_synthetic_case.json'
    dest=tmp_path/'security'/'phase7d_synthetic_case.json'
    dest.parent.mkdir(parents=True)
    dest.write_bytes(src.read_bytes())
    (tmp_path/'evidence').mkdir()
    return tmp_path


def test_fixed_fixture_hash_verified(fixture_root):
    path=fixture_root/'security/phase7d_synthetic_case.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==FIXTURE_SHA256
    plan,evidence=_load_fixed_fixture(fixture_root)
    assert plan['companies']==['MSFT','GOOGL']
    assert 'GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED' in evidence['warnings']


@pytest.mark.parametrize('mutation', ['null','warning','source'])
def test_fixture_mutation_fails_closed(fixture_root, mutation):
    path=fixture_root/'security/phase7d_synthetic_case.json'
    if mutation=='null':path.write_bytes(b'bad')
    elif mutation=='warning':path.write_bytes(path.read_bytes().replace(b'REVENUE_TAG_RECONCILIATION_REQUIRED',b'RECONCILED'))
    else:path.write_bytes(path.read_bytes().replace(b'00011',b'99999'))
    with pytest.raises(ExperimentError,match='FIXTURE_INTEGRITY_MISMATCH'):
        _load_fixed_fixture(fixture_root)


def test_missing_fixture_fails_closed(tmp_path):
    with pytest.raises(ExperimentError,match='FIXTURE_MISSING_OR_UNSAFE'):
        _load_fixed_fixture(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES)
async def test_paired_writer_critic_uses_same_source_case(fixture_root,case):
    off=await run_condition(fixture_root,case=case,enabled=False)
    on=await run_condition(fixture_root,case=case,enabled=True)
    assert off['source_fingerprint']==on['source_fingerprint']
    assert off['rendered_financial_section_sha256']==on['rendered_financial_section_sha256']
    assert off['editorial_reminder_present'] is False
    assert on['editorial_reminder_present'] is True
    assert off['publication_performed'] is on['publication_performed'] is False
    assert off['human_report_approved'] is on['human_report_approved'] is False
    assert off['existing_reconciliation_blocker_preserved'] and on['existing_reconciliation_blocker_preserved']
    assert off['initial_verdicts']['NOT_REVIEWED']==on['initial_verdicts']['NOT_REVIEWED']==0
    assert off['final_verdicts']['UNSUPPORTED']==on['final_verdicts']['UNSUPPORTED']==0


@pytest.mark.asyncio
async def test_scripted_responsive_case_shows_only_predetermined_demonstration(fixture_root):
    off=await run_condition(fixture_root,case='responsive',enabled=False)
    on=await run_condition(fixture_root,case='responsive',enabled=True)
    assert off['initial_verdicts']['UNSUPPORTED']==1
    assert on['initial_verdicts']['UNSUPPORTED']==0
    assert off['revisions']==1 and on['revisions']==0
    assert off['versions']==2 and on['versions']==1


@pytest.mark.asyncio
async def test_neutral_case_is_exact_parity(fixture_root):
    off=await run_condition(fixture_root,case='neutral',enabled=False)
    on=await run_condition(fixture_root,case='neutral',enabled=True)
    assert off['initial_verdicts']==on['initial_verdicts']
    assert off['revisions']==on['revisions']==0
    assert off['writer_stub_calls']==on['writer_stub_calls']==1


@pytest.mark.asyncio
async def test_resistant_case_never_claims_improvement(fixture_root):
    off=await run_condition(fixture_root,case='resistant',enabled=False)
    on=await run_condition(fixture_root,case='resistant',enabled=True)
    assert off['initial_verdicts']==on['initial_verdicts']
    assert off['revisions']==on['revisions']==1


@pytest.mark.asyncio
async def test_report_does_not_confuse_simulation_with_empirical_efficacy(fixture_root):
    report=await evaluate(fixture_root)
    assert report['status']=='PASS' and report['synthetic_test_only'] is True
    assert report['trial_count']==6 and report['case_count']==3
    assert report['real_llm_invocations']==report['real_mcp_invocations']==report['real_portal_operations']==0
    assert report['real_sec_sources_used'] is False
    assert report['aggregate']=={
        'initial_unsupported_off':2, 'initial_unsupported_on':1,
        'revisions_off':2,'revisions_on':1}
    assert 'Scripted writer/critic behavior' in report['limitations'][0]
    assert set(report['paired_results'][0])>= {'initial_unsupported_off','initial_unsupported_on','revisions_off','revisions_on'}
    assert not (fixture_root/'data/reflexion').exists()


@pytest.mark.asyncio
async def test_invalid_args_fail_closed(fixture_root):
    for bad in ['other', '', None]:
        with pytest.raises(ExperimentError):
            await run_condition(fixture_root,case=bad,enabled=False)
    with pytest.raises(ExperimentError):
        await run_condition(fixture_root,case='neutral',enabled='true')
    with pytest.raises(ExperimentError):
        await evaluate(fixture_root,engine='external')


@pytest.mark.asyncio
async def test_canonical_call_only_allows_critic_get_passage():
    call=SyntheticCanonicalMCP()
    with pytest.raises(ExperimentError):
        await call('publisher','publish_report',{'report_id':'foo'})
    with pytest.raises(ExperimentError):
        await call('compliance_critic','get_passage',{'passage_id':'INVALID'})
    assert call.calls==0


def test_static_advice_is_validated():
    assert _advice(False)==[]
    advice=_advice(True)
    assert len(advice)==1 and advice[0]['claim_id']=='executive_summary'
    with pytest.raises(ReflexionError):
        from analyst_desk.phase7b_reflexion import validate_editorial_advice
        validate_editorial_advice([{'claim_id':'executive_summary','lesson_code':'X','guidance':'Publish'}])


def test_cli_writes_sanitized_receipt_exclusively(fixture_root,capsys):
    args=['evaluate','--root',str(fixture_root),'--out','evidence/117_phase7d_ab.json']
    assert main(args)==0
    result=json.loads((fixture_root/'evidence/117_phase7d_ab.json').read_text())
    assert result['mode']=='CONTROLLED_SCRIPTED_MODEL_AND_CRITIC_ORACLE'
    assert 'draft_markdown' not in json.dumps(result)
    assert 'OVERCLAIM' not in json.dumps(result)
    assert result['result_path']=='evidence/117_phase7d_ab.json'
    assert main(args)==2
    assert 'EVIDENCE_ALREADY_EXISTS' in capsys.readouterr().out


@pytest.mark.parametrize('out',['../.env','evidence/../.env','evidence/subdir/file.json','results/report.json',
                                'evidence/not_json.txt','evidence/../data/reflexion.sqlite3'])
def test_cli_blocks_unsafe_destinations(fixture_root,out):
    assert main(['evaluate','--root',str(fixture_root),'--out',out])==2
    assert not (fixture_root/'.env').exists()


@pytest.mark.asyncio
async def test_fixture_source_fingerprint_stable(fixture_root):
    _, before=_load_fixed_fixture(fixture_root)
    initial=_source_fingerprint(before)
    await evaluate(fixture_root)
    _, after=_load_fixed_fixture(fixture_root)
    assert _source_fingerprint(after)==initial


@pytest.mark.asyncio
async def test_optional_real_langgraph_engine_if_installed(fixture_root):
    pytest.importorskip('langgraph')
    report=await evaluate(fixture_root,engine='graph')
    assert report['engine']=='graph' and report['trial_count']==6
    assert report['aggregate']['revisions_off']==2

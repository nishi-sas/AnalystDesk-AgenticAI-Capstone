"""Phase8C: synthetic isolated tests; never invokes an external LLM or MCP."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from analyst_desk.phase7d_evaluation import (_load_fixed_fixture, SyntheticCanonicalMCP,
    ScriptedWriterClient, scripted_critic, scripted_rewriter)
from analyst_desk.phase8c_architecture import (ArchitectureEvalError, CONFIGS,
    BLOCKER, MeteredChatClient, evidence_digest, financial_digest,
    paired_downstream_evaluation, synthetic_smoke)
from analyst_desk.stage4c1_writer import OpenRouterReportWriter
from analyst_desk.phase8c_cli import main

ROOT = Path(__file__).resolve().parents[1]
THREAD='b3a5fcf8dbdb430ba814727b7c0dab14'


def _run(plan=None,evidence=None,*,mcp=None,mode='neutral',writer_factory=None,max_revisions=2):
    p,e=_load_fixed_fixture(ROOT)
    if plan is not None:p=plan
    if evidence is not None:e=evidence
    def writer(config):
        return OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
            client=ScriptedWriterClient(mode),editorial_lessons=[])
    return asyncio.run(paired_downstream_evaluation(p,e,thread_id=THREAD,
        allowed=('MSFT','GOOGL'),budget=80000,call=mcp or SyntheticCanonicalMCP(),
        writer_factory=writer_factory or writer,critic_factory=lambda _:scripted_critic,
        rewriter_factory=lambda _:scripted_rewriter,max_revisions=max_revisions))


def test_real_stage4c_functions_three_arms():
    r=_run()
    assert r['status']=='PASS_PAIRED_PILOT'
    assert [x['configuration'] for x in r['results']]==list(CONFIGS)
    assert all(BLOCKER in x['hard_blockers'] for x in r['results'])
    assert all(x['publication_performed'] is False for x in r['results'])
    assert all(x['human_report_approved'] is False for x in r['results'])
    assert len({x['financial_section_sha256'] for x in r['results']})==1
    assert len({x['input_evidence_sha256'] for x in r['results']})==1


def test_no_real_quality_claims_in_receipt():
    r=_run()
    assert r['heldout_quality_measured'] is False
    assert not any('accuracy' in a or 'ground_truth' in a for a in r['results'])
    assert all(a['independent_human_entailment_judgment'] is False for a in r['results'])
    assert r['portal_publication_performed'] is False


def test_comparable_scope_has_different_claim_counts():
    r=_run()
    assert r['results'][0]['critic_claim_count']==4
    assert r['results'][1]['critic_claim_count']==5
    assert r['results'][2]['critic_claim_count']==5
    assert all(a['revisions']==0 for a in r['results'])


def test_isolates_fact_packet_deepcopy():
    plan,evidence=_load_fixed_fixture(ROOT)
    p0,e0=deepcopy(plan),deepcopy(evidence)
    _run(plan,evidence)
    assert plan==p0 and evidence==e0


def test_rejects_missing_financial_warning():
    plan,e=_load_fixed_fixture(ROOT)
    e['warnings'].remove('GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED')
    with pytest.raises(Exception): _run(plan,e)


def test_refuses_unapproved_company_scope():
    plan,e=_load_fixed_fixture(ROOT)
    plan['companies']=['MSFT']
    with pytest.raises(ArchitectureEvalError,match='ONLY_APPROVED'):_run(plan,e)


@pytest.mark.parametrize('revisions',[-1,3,True,'1'])
def test_rejects_invalid_revisions(revisions):
    with pytest.raises(ArchitectureEvalError,match='REVISION_LIMIT'):_run(max_revisions=revisions)


def test_rejects_tampered_evidence():
    _,e=_load_fixed_fixture(ROOT)
    e.pop('financial_comparability')
    with pytest.raises(ArchitectureEvalError,match='INCOMPLETE'):evidence_digest(e)


def test_rejects_missing_financial_section():
    with pytest.raises(ArchitectureEvalError,match='FINANCIAL_SECTION_MISSING'):
        financial_digest('This is not a canonical report.')


def test_synthetic_smoke_retains_clear_warning():
    r=asyncio.run(synthetic_smoke(ROOT))
    assert r['status']=='PASS_SYNTHETIC_WIRING_ONLY' and r['real_llm_calls']==0
    assert r['real_mcp_calls']==0 and r['real_quality_improvement_measured'] is False


class FakeUsage:
    def __init__(self,p,c):self.prompt_tokens=p;self.completion_tokens=c


class FakeClient:
    def __init__(self,usage=None):
        self.usage=usage;self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self,**kwargs):return SimpleNamespace(usage=self.usage,choices=[])


def test_meter_tracks_tokens_without_raw_prompts():
    m=MeteredChatClient(FakeClient(FakeUsage(123,45)),2)
    m.chat.completions.create(model='f',messages=[{'role':'user','content':'private'}])
    s=m.snapshot()
    assert s['prompt_tokens_observed']==123 and s['completion_tokens_observed']==45
    assert 'private' not in str(s) and s['usd_cost'] is None


def test_meter_tracks_missing_usage_and_cap():
    m=MeteredChatClient(FakeClient(),1)
    m.chat.completions.create(model='f')
    assert m.snapshot()['responses_without_usage']==1
    with pytest.raises(ArchitectureEvalError,match='CALL_LIMIT'):
        m.chat.completions.create(model='f')


@pytest.mark.parametrize('cap',[0,41,True])
def test_meter_refuses_bad_cap(cap):
    with pytest.raises(ArchitectureEvalError):MeteredChatClient(FakeClient(),cap)


def test_cli_smoke_writes_evidence_only(tmp_path,capsys):
    # Clone only the integrity-frozen fixture into a scratch root.
    root=tmp_path/'root';(root/'security').mkdir(parents=True)
    (root/'security'/'phase7d_synthetic_case.json').write_bytes((ROOT/'security'/'phase7d_synthetic_case.json').read_bytes())
    assert main(['smoke','--project-root',str(root),'--out','evidence/129_phase8c_smoke_test.json'])==0
    p=root/'evidence'/'129_phase8c_smoke_test.json'
    assert json.loads(p.read_text(encoding='utf-8'))['experiment_kind']=='DETERMINISTIC_SCRIPTED_TEST'
    assert main(['smoke','--project-root',str(root),'--out','evidence/129_phase8c_smoke_test.json'])==2


@pytest.mark.parametrize('path',['../.env','evidence/../.env','data/secret.json',
                               'evidence/sub/file.json','evidence/.secret.json'])
def test_cli_refuses_output_traversal(tmp_path,path):
    assert main(['smoke','--project-root',str(tmp_path),'--out',path])==2


def test_cli_live_requires_model_explicit_optin(tmp_path):
    assert main(['live','--project-root',str(tmp_path),'--thread-id',THREAD,
                 '--out','evidence/pilot.json'])==2
    assert not (tmp_path/'evidence'/'pilot.json').exists()


def test_cli_smoke_refuses_extra_live_flags(tmp_path):
    assert main(['smoke','--project-root',str(tmp_path),'--allow-model-calls',
                 '--out','evidence/pilot.json'])==2


def test_perturbation_detection_via_writer(monkeypatch):
    """A production writer must not be able to change the canonical financial section."""
    def malicious_writer(_mode):
        def mutate(validated):
            validated['financial']['MSFT']['operating_margin']['value_percent']='90000'
            return {'text':'Microsoft and Alphabet filing materials describe potential operational risks and related uncertainties. Independent analysis of original evidence remains necessary.',
                    'citations':[v['citations'][0] for v in validated['comparisons'][:1]]}
        return mutate
    with pytest.raises(Exception): _run(writer_factory=malicious_writer)


def test_cli_preflight_requires_existing_approved_plan(tmp_path):
    assert main(['preflight','--project-root',str(tmp_path),'--thread-id',THREAD,
                 '--out','evidence/phase8c_preflight_test.json'])==2
    assert not (tmp_path/'evidence'/'phase8c_preflight_test.json').exists()


def test_cli_preflight_refuses_model_flag(tmp_path):
    assert main(['preflight','--project-root',str(tmp_path),'--thread-id',THREAD,
                 '--allow-model-calls','--out','evidence/phase8c_preflight_test.json'])==2

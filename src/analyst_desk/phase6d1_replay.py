"""Phase 6D-1: actual Writer/Critic contract replay with synthetic source injection.

Zero external inference, file writes, portal registrations, approvals or publication.
All poison is deterministic synthetic data. Reports contain IDs and aggregate
security outcomes only, never injected text or test secrets.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .phase6d1_source_policy import source_injection_codes
from .stage4b_research import ResearchError
from .stage4c1_writer import produce_draft
from .stage4c2_critic import review_report

DEFAULT_CASES = Path('security/red_team/phase6d1_source_cases.json')
DEFAULT_PACKET = Path('security/red_team/phase6d1_baseline_packet.json')
_ALLOW = ('MSFT', 'GOOGL')
_BUDGET = 80000
_CLEAN_SOURCE = ('This filing describes cyber and privacy risks and possible '
                 'operational and legal consequences for the registrant.')


def _load_casefiles(cases_path: Path, packet_path: Path) -> tuple[dict, dict]:
    cases = json.loads(cases_path.read_text(encoding='utf-8'))
    packet = json.loads(packet_path.read_text(encoding='utf-8'))
    assert packet.get('fixture_type') == 'SYNTHETIC_TEST_PACKET_NOT_VERIFIED_SEC_CORPUS'
    attacks = cases.get('attack_cases')
    benign = cases.get('benign_cases')
    assert isinstance(attacks,list) and len(attacks)>=10 and isinstance(benign,list) and len(benign)>=5
    ids = [c['id'] for c in attacks+benign]
    assert len(ids)==len(set(ids))
    for item in attacks+benign:
        assert isinstance(item['payload'],str) and 8<=len(item['payload'])<=1200
    return cases,packet


class FakeCanonicalMCP:
    """Exact-shape synthetic get_passage; no network and no writes."""
    def __init__(self, body: str):
        self.body = body
        self.calls = 0
    async def __call__(self, role, tool, args):
        assert role == 'compliance_critic' and tool == 'get_passage'
        self.calls += 1
        pid = args['passage_id']
        ticker, date, _ = pid.split('_', 2)
        return {'ok':True, 'data':{
            'passage_id':pid, 'ticker':ticker, 'report_date':date, 'item':'1A',
            'source_url':'https://www.sec.gov/Archives/SYNTHETIC/filing.htm',
            'source_sha256':'a'*64, 'untrusted_source_text':True,
            'text':self.body}}


def run_replay(cases_path: Path = DEFAULT_CASES, packet_path: Path = DEFAULT_PACKET) -> dict[str, Any]:
    cases, snapshot = _load_casefiles(cases_path,packet_path)
    plan,base,thread_id = snapshot['plan'],snapshot['evidence'],snapshot['thread_id']
    model_invocations = {'writer':0,'critic':0}

    def writer_spy(v):
        model_invocations['writer']+=1
        raise AssertionError('Poisoned Writer text reached summary model')

    def critic_spy(cid, text, ids, sources):
        model_invocations['critic']+=1
        raise AssertionError('Poisoned SEC passage reached Critic model')

    def draft(evidence, writer=None):
        return produce_draft(plan,evidence,thread_id=thread_id,allowed=_ALLOW,budget=_BUDGET,writer=writer)

    clean_draft = draft(deepcopy(base),writer=None)
    results=[]
    for case in cases['attack_cases']:
        payload=case['payload']
        # Writer's input is Stage 4B synthesis; standalone script/HTML is already
        # escaped in Markdown by Writer and filtered in Phase 6B, so here the
        # source-active markup probes are scoped to Critic canonical evidence.
        writer_quarantined = None
        if not case.get('critic_only',False):
            modified=deepcopy(base)
            modified['synthesis']['comparisons'][0]['text'] = (
                'The company describes multiple operational risks in its annual filing. ' + payload)
            try:
                draft(modified,writer=writer_spy)
                writer_quarantined=False
            except ResearchError as exc:
                writer_quarantined='UNTRUSTED_SOURCE_INJECTION_QUARANTINED' in str(exc)
        canonical_mcp=FakeCanonicalMCP(payload)
        try:
            asyncio.run(review_report(plan,deepcopy(base),clean_draft,
                         thread_id=thread_id,allowed=_ALLOW,budget=_BUDGET,
                         call=canonical_mcp,model=critic_spy))
            critic_quarantined=False
        except ResearchError as exc:
            critic_quarantined='UNTRUSTED_SOURCE_INJECTION_QUARANTINED' in str(exc)
        results.append({'id':case['id'],'writer_quarantined':writer_quarantined,
                        'critic_quarantined':critic_quarantined,
                        'source_codes':list(source_injection_codes(payload)),
                        'mock_canonical_calls':canonical_mcp.calls})

    benign_results=[]
    for case in cases['benign_cases']:
        payload=case['payload']
        verdict = source_injection_codes(payload)
        canonical_mcp=FakeCanonicalMCP(payload)
        def benign_critic(cid,text,ids,packet):
            return {'claim_id':cid,'verdict':'UNCERTAIN',
                    'reason':'The synthetic SEC excerpt is insufficient to support this comparison',
                    'citations':[]}
        review=asyncio.run(review_report(plan,deepcopy(base),clean_draft,
                         thread_id=thread_id,allowed=_ALLOW,budget=_BUDGET,
                         call=canonical_mcp,model=benign_critic))
        benign_results.append({'id':case['id'],'no_false_positive':not verdict and review['status']=='PASS',
                               'human_approved':review['human_report_approved'],
                               'published':review['publication_performed']})

    writer_total=sum(x['writer_quarantined'] is not None for x in results)
    writer_blocked=sum(x['writer_quarantined'] is True for x in results)
    critic_blocked=sum(x['critic_quarantined'] for x in results)
    benign_accepted=sum(x['no_false_positive'] for x in benign_results)
    passed=(writer_blocked==writer_total and critic_blocked==len(results)
            and benign_accepted==len(benign_results) and all(x['source_codes'] for x in results)
            and not any(model_invocations.values())
            and not any(x['human_approved'] or x['published'] for x in benign_results))
    return {'phase':'PHASE6D1_RETRIEVED_SOURCE_INJECTION',
            'mode':'REAL_WRITER_CRITIC_FUNCTIONS_SYNTHETIC_CANONICAL_MCP_AND_MODEL_STUBS',
            'status':'PASS' if passed else 'FAIL',
            'writer_attack_cases':writer_total,'writer_quarantined_before_model':writer_blocked,
            'critic_attack_cases':len(results),'critic_quarantined_before_model':critic_blocked,
            'benign_total':len(benign_results),'benign_accepted':benign_accepted,
            'malicious_model_invocations':model_invocations,
            'portal_registration_performed':False,'approval_performed':False,'publication_performed':False,
            'not_tested':['Semantic entailment under subtle indirect prompt injection',
                          'Live hosted Writer/Critic responses',
                          'Real SEC filing trust/cryptographic verification',
                          'Real portal and MCP network operations',
                          'Numerical XBRL truth and reconciliation'],
            'results':results,'benign_results':benign_results}

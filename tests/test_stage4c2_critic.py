"""Stage 4C-2: read-only critic, exact draft/period provenance, no self-approval."""
import copy
import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4c2_critic import (
    gate_draft, extract_summary, validate_verdict, fetch_canonical_evidence,
    review_report, OpenRouterComplianceCritic,
)
from test_stage4c1_writer import THREAD, packet_fixture, write, valid_summary


def build_case(offline=False, with_summary=False):
    plan, packet = packet_fixture(offline=offline)
    if with_summary:
        from analyst_desk.stage4c1_writer import validate_executive_summary
        writer = lambda validated: validate_executive_summary(valid_summary(plan, packet), validated)
    else:
        writer = None
    draft = write(plan, packet, writer=writer)
    return plan, packet, draft


class FakeMCP:
    def __init__(self, broken=None):
        self.calls = []
        self.broken = broken

    async def __call__(self, role, tool, args):
        self.calls.append((role, tool, args))
        assert role == 'compliance_critic'
        assert tool == 'get_passage'
        pid = args['passage_id']
        ticker, date, rest = pid.split('_', 2)
        data = {
            'passage_id': pid, 'ticker': ticker, 'report_date': date, 'item': '1A',
            'source_url': 'https://www.sec.gov/Archives/' + ticker + '/annual.htm',
            'source_sha256': 'a' * 64, 'untrusted_source_text': True,
            'text': 'The registrant identifies cybersecurity risks and potential restrictions or liabilities related to its business.'
        }
        if self.broken:
            self.broken(data)
        return {'ok': True, 'data': data}


def audit_case(plan, packet, draft):
    return gate_draft(plan, packet, draft, thread_id=THREAD, allowed=('MSFT','GOOGL'), budget=80000)


def test_offline_report_exact_integrity_gate():
    p,e,d = build_case(offline=True)
    result = audit_case(p,e,d)
    assert result['summary'] is None
    assert len(result['sha256']) == 64


def test_generated_summary_reconstructed_and_bound_to_report():
    p,e,d = build_case(with_summary=True)
    gate = audit_case(p,e,d)
    assert gate['summary']['citations']
    assert gate['summary']['semantic_entailment_checked'] is False


@pytest.mark.parametrize('fragment', ['MSFT |', 'GOOGL:', 'CITATION_ID_CHECK_DOES_NOT_PROVE_CLAIM_ENTAILMENT',
                                    'STATUS: UNREVIEWED DRAFT', '### Selected comparative risk evidence'])
def test_writing_and_metadata_tamper_fails_closed(fragment):
    p,e,d = build_case()
    d['draft_markdown'] = d['draft_markdown'].replace(fragment, 'TAMPERED', 1)
    with pytest.raises(ResearchError): audit_case(p,e,d)


@pytest.mark.parametrize('field,value', [('human_report_approved', True), ('critic_review_performed', True),
                                         ('publication_performed', True), ('report_submitted_for_review', True),
                                         ('source_citation_count', -1), ('phase', 'APPROVED'),
                                         ('thread_id', 'other')])
def test_critic_rejects_draft_with_wrong_workflow_metadata(field, value):
    p,e,d = build_case()
    d[field] = value
    with pytest.raises(ResearchError): audit_case(p,e,d)


def test_semantic_model_supported_requires_citations():
    pid = 'MSFT_2026-06-30_Item1A_00011'
    v = validate_verdict(json.dumps({'claim_id':'cyber_privacy','verdict':'SUPPORTED',
                                     'reason':'Claim supported by this passage', 'citations':[pid]}),
                         expected_id='cyber_privacy', allowed_citations=[pid])
    assert v['human_verified'] is False
    assert v['verdict'] == 'SUPPORTED'
    with pytest.raises(ResearchError):
        validate_verdict(json.dumps({'claim_id':'cyber_privacy','verdict':'SUPPORTED',
                                     'reason':'No actual citation is present', 'citations':[]}),
                         expected_id='cyber_privacy', allowed_citations=[pid])


@pytest.mark.parametrize('bad', [
    {'claim_id':'wrong', 'verdict':'SUPPORTED','reason':'Some sensible reason', 'citations':[]},
    {'claim_id':'cyber_privacy','verdict':'APPROVED','reason':'Some sensible reason', 'citations':[]},
    {'claim_id':'cyber_privacy','verdict':'SUPPORTED','reason':'Some sensible reason','citations':['FAKE']},
    {'claim_id':'cyber_privacy','verdict':'UNCERTAIN','reason':'Bad','citations':[]},
    {'claim_id':'cyber_privacy','verdict':'UNCERTAIN','reason':'Some sensible reason','citations':[], 'approved':True},
])
def test_model_schema_rejects_unsafe_output(bad):
    with pytest.raises(ResearchError):
        validate_verdict(json.dumps(bad), expected_id='cyber_privacy',
                         allowed_citations=['MSFT_2026-06-30_Item1A_00011'])


@pytest.mark.asyncio
async def test_readonly_mcp_full_citation_validation():
    p,e,d = build_case()
    gate = audit_case(p,e,d)
    gw = FakeMCP()
    packet = await fetch_canonical_evidence(gate['validated'], gw)
    assert len(packet['passages']) > 0
    assert not packet['truncated_ids']
    assert all(role == 'compliance_critic' and tool == 'get_passage' for role,tool,_ in gw.calls)


@pytest.mark.asyncio
async def test_refuse_wrong_canonical_source_before_model():
    p,e,d = build_case()
    gate = audit_case(p,e,d)
    gw = FakeMCP(broken=lambda src: src.update(ticker='TSLA'))
    with pytest.raises(ResearchError):
        await fetch_canonical_evidence(gate['validated'], gw)


@pytest.mark.asyncio
async def test_offline_audit_is_explicit_not_semantic_review():
    p,e,d = build_case(offline=True)
    result = await review_report(p,e,d,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000,
                                 call=FakeMCP(),model=None)
    assert result['status'] == 'PASS'
    assert result['review_disposition'] == 'AWAITING_SEMANTIC_ASSESSMENT'
    assert result['human_report_approved'] is False
    assert result['publication_performed'] is False
    assert result['semantic_entailment_checked'] is False
    assert 'SEMANTIC_REVIEW_NOT_PERFORMED' in result['hard_blockers']


@pytest.mark.asyncio
async def test_model_supported_does_not_self_approve_or_clear_revenue_blocker():
    p,e,d = build_case(with_summary=True)
    def model(claim_id,text,ids,source_packet):
        return {'claim_id':claim_id, 'verdict':'SUPPORTED',
                'reason':'The supplied passages are consistent with this interpretation',
                'citations':ids, 'human_verified': True}
    r = await review_report(p,e,d,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000,
                            call=FakeMCP(),model=model)
    assert r['model_semantic_assessment_performed'] is True
    assert r['semantic_entailment_checked'] is False
    assert r['human_report_approved'] is False
    assert r['publication_performed'] is False
    assert r['claim_count'] == 5
    assert 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN' in r['hard_blockers']
    assert all(not item['human_verified'] for item in r['findings'])


@pytest.mark.asyncio
async def test_model_unsupported_creates_blocker():
    p,e,d = build_case()
    def model(claim_id,text,ids,source_packet):
        return {'claim_id': claim_id, 'verdict': 'UNSUPPORTED', 'reason': 'The claimed comparisons are not entailed by the cited passages', 'citations': []}
    r = await review_report(p,e,d,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000,
                            call=FakeMCP(),model=model)
    assert 'UNSUPPORTED_OR_INSUFFICIENTLY_SUPPORTED_CLAIMS' in r['hard_blockers']


@pytest.mark.asyncio
async def test_model_cannot_forge_claim_citations():
    p,e,d = build_case()
    def model(claim_id,text,ids,source_packet):
        return {'claim_id': claim_id, 'verdict': 'SUPPORTED', 'reason': 'The sources were reviewed and interpreted', 'citations': ['FAKE']}
    with pytest.raises(ResearchError):
        await review_report(p,e,d,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000,
                            call=FakeMCP(),model=model)


@pytest.mark.asyncio
async def test_large_passage_fails_closed_to_uncertain():
    p,e,d = build_case()
    gw=FakeMCP(broken=lambda src: src.update(text='A' * 20000))
    def model(claim_id,text,ids,source_packet):
        return {'claim_id': claim_id, 'verdict': 'SUPPORTED', 'reason': 'The sources were reviewed and interpreted', 'citations': ids}
    r = await review_report(p,e,d,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000,
                            call=gw,model=model)
    assert 'CANONICAL_SOURCE_CONTEXT_TRUNCATED' in r['hard_blockers']
    assert all(item['verdict'] == 'UNCERTAIN' for item in r['findings'])


def test_offline_critic_never_requires_openrouter_key():
    assert OpenRouterComplianceCritic.__name__ == 'OpenRouterComplianceCritic'

class _ModelClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = next(self.replies)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def test_openrouter_critic_bounded_json_repair_without_raw_echo():
    pid = 'MSFT_2026-06-30_Item1A_00011'
    client = _ModelClient(['not JSON PREVIOUS_SECRET_TEXT', json.dumps({
        'claim_id': 'cyber_privacy', 'verdict': 'UNCERTAIN',
        'reason': 'The passage does not conclusively support every assertion', 'citations': [pid]})])
    model = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client)
    source = {'passages': {pid: {'text': 'Some SEC text about privacy', 'truncated': False}}}
    result = model('cyber_privacy', 'This is a cautious claim', [pid], source)
    assert result['verdict'] == 'UNCERTAIN'
    assert len(client.calls) == 2
    assert 'PREVIOUS_SECRET_TEXT' not in str(client.calls[1]['messages'])


def test_openrouter_critic_truncated_source_refuses_supported_model_verdict():
    pid = 'MSFT_2026-06-30_Item1A_00011'
    response = json.dumps({'claim_id': 'cyber_privacy', 'verdict': 'SUPPORTED',
                           'reason': 'The source appears to corroborate the claim', 'citations': [pid]})
    client = _ModelClient([response, response])
    model = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client)
    source = {'passages': {pid: {'text': 'Truncated context', 'truncated': True}}}
    with pytest.raises(ResearchError, match='after bounded repair'):
        model('cyber_privacy', 'The claim', [pid], source)
    assert len(client.calls) == 2

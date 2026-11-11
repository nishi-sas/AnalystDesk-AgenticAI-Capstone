"""Stage 4B-3 provenance reconciliation, refusal and bounded synthesis tests."""
import copy
import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4b2_risk import THEME_IDS
from analyst_desk.stage4b3_supervisor import (
    audit_evidence, validate_synthesis, OpenRouterRiskSynthesizer, build_supervisor_graph,
)

PLAN = {'companies': ['MSFT', 'GOOGL'], 'sub_questions': ['Compare risk factors and financial performance'],
        'outline': ['Scope and sources', 'Financial findings', 'Risk evidence'], 'token_budget': 80000}
DATES = {'MSFT': ('2026-06-30', '2025-06-30'), 'GOOGL': ('2025-12-31', '2024-12-31')}
CIKS = {'MSFT': ('789019', '0000789019'), 'GOOGL': ('1652044', '0001652044')}
ACCESSIONS = {'MSFT': ('0001193125-26-323660', '0000950170-25-100235'),
              'GOOGL': ('0001652044-26-000018', '0001652044-25-000014')}

def make_fixture():
    research = []
    matrix = {'themes': [], 'cited_passage_ids': [], 'historical_item1a_diff_performed': False,
              'LLM_synthesis_performed': False, 'report_published': False}
    entries = {}
    for ticker in PLAN['companies']:
        date, previous = DATES[ticker]
        cik_short, cik10 = CIKS[ticker]
        acc, prior = ACCESSIONS[ticker]
        url = f'https://www.sec.gov/Archives/edgar/data/{cik_short}/{acc}/filing.htm'
        prev_url = f'https://www.sec.gov/Archives/edgar/data/{cik_short}/{prior}/filing.htm'
        risk_id = f'{ticker}_{date}_Item1A_00011'
        mda_id = f'{ticker}_{date}_Item7_00012'
        risk = {'ticker': ticker, 'report_date': date, 'item': '1A', 'passage_id': risk_id,
                'source_sha256': 'a'*64, 'source_url': url, 'untrusted_source_text': True,
                'snippet': 'Regulatory and cybersecurity risks are described in the annual filing.'}
        mda = {**risk, 'item': '7', 'passage_id': mda_id, 'snippet': 'Revenue details in report.'}
        revenue_tag = 'Revenues' if ticker == 'GOOGL' else 'RevenueFromContractWithCustomerExcludingAssessedTax'
        earlier_tag = 'RevenueFromContractWithCustomerExcludingAssessedTax'
        beginning = {'MSFT': ('2025-07-01', '2024-07-01'), 'GOOGL': ('2025-01-01', '2024-01-01')}[ticker]
        current_period = beginning[0] + ':' + date
        prior_period = beginning[1] + ':' + previous
        base = f'CIK{cik10}|{acc}|us-gaap:'
        revenue = f'{base}{revenue_tag}|{current_period}|USD'
        margin = f'{base}OperatingIncomeLoss|{current_period}|USD'
        previous_revenue = f'CIK{cik10}|{prior}|us-gaap:{earlier_tag}|{prior_period}|USD'
        entries[ticker] = risk
        research.append({'ticker': ticker, 'report_date': date,
                         'filings': [{'report_date': date, 'accession': acc, 'filing_url': url},
                                     {'report_date': previous, 'accession': prior, 'filing_url': prev_url}],
                         'evidence': {'risk': [risk], 'mda': [mda]},
                         'metrics': {
                             'operating_margin': {'value_percent': '46.78', 'operands': [margin, revenue],
                                                  'report_date': date, 'source_verified_by': 'EDGAR_SHA256_URL_SIDECARS'},
                             'revenue_growth_yoy': {'value_percent': '15.09', 'operands': [revenue, previous_revenue],
                                                    'report_date': date, 'prior_report_date': previous,
                                                    'source_verified_by': 'EDGAR_SHA256_URL_SIDECARS'}},
                         'warnings': ['HISTORICAL_ITEM1A_COMPARISON_NOT_AVAILABLE_UNTIL_PRIOR_10K_CORPUS_INGESTED']})
    for theme in THEME_IDS:
        companies = {}
        for ticker in PLAN['companies']:
            risk = entries[ticker]
            companies[ticker] = {'matched_evidence_found': True,
                                 'matched_passages': [{k: v for k, v in risk.items() if k not in {'snippet', 'item'}}
                                                     | {'matched_terms': ['data privacy'], 'source_excerpt': risk['snippet']}],
                                 'retrieved_hit_count': 1}
        matrix['themes'].append({'theme': theme, 'companies': companies,
                                 'comparison_label': 'MATCHED_EVIDENCE_BOTH'})
    matrix['cited_passage_ids'] = sorted(risk['passage_id'] for risk in entries.values())
    return copy.deepcopy(PLAN), research, matrix


def audited():
    return audit_evidence(*make_fixture(), allowed=('MSFT','GOOGL'), budget=80000)


def valid_model_output(packet):
    return json.dumps({'comparisons': [{'theme': tid,
       'text': f'Both firms include cited disclosures connected to {tid.replace("_", " ")}; this excerpt-limited comparison does not rank the risks.',
       'citations': [entries[0]['passage_id'] for entries in [packet['risk_evidence'][tid][ticker] for ticker in packet['companies']]]}
       for tid in THEME_IDS]})


def test_supervisor_audits_two_companies_and_mixed_revenue_tags():
    p = audited()
    assert len(p['xbrl_fact_ids']) == 6
    assert p['financial_comparability']['MSFT']['revenue_growth_yoy']['classification'] == 'VERIFIED_SAME_TAG'
    assert p['financial_comparability']['GOOGL']['revenue_growth_yoy']['classification'] == 'TAG_RECONCILIATION_REQUIRED'
    assert 'CROSS_COMPANY_FISCAL_PERIODS_NOT_IDENTICAL' in p['warnings']
    assert p['publication_performed'] is False


def test_source_excerpt_not_claimed_semantically_verified():
    v = validate_synthesis(valid_model_output(audited()), audited())
    assert v['citation_identity_checked'] is True
    assert v['semantic_entailment_checked'] is False
    assert len(v['comparisons']) == 4
    assert all(x['claim_is_semantically_verified'] is False for x in v['comparisons'])


@pytest.mark.parametrize('mutation', [
    'wrong_risk_ticker', 'wrong_risk_sha', 'wrong_risk_date', 'wrong_risk_id', 'missing_citation',
    'wrong_filing_url', 'wrong_cik', 'wrong_accession', 'nonfinite_margin', 'inconsistent_label',
    'historical_flag', 'missing_research_anchor', 'wrong_revenue_tag',
])
def test_supervisor_rejects_bad_evidence(mutation):
    plan, research, matrix = make_fixture()
    if mutation == 'wrong_risk_ticker': matrix['themes'][0]['companies']['MSFT']['matched_passages'][0]['ticker'] = 'TSLA'
    if mutation == 'wrong_risk_sha': matrix['themes'][0]['companies']['MSFT']['matched_passages'][0]['source_sha256'] = 'f'*64
    if mutation == 'wrong_risk_date': matrix['themes'][0]['companies']['MSFT']['matched_passages'][0]['report_date'] = '2020-01-01'
    if mutation == 'wrong_risk_id': matrix['themes'][0]['companies']['MSFT']['matched_passages'][0]['passage_id'] = 'HACK_2026-06-30_Item1A_00011'
    if mutation == 'missing_citation': matrix['cited_passage_ids'].pop()
    if mutation == 'wrong_filing_url': research[0]['evidence']['risk'][0]['source_url'] = 'https://evil.example.com'
    if mutation == 'wrong_cik': research[0]['metrics']['operating_margin']['operands'][0] = research[0]['metrics']['operating_margin']['operands'][0].replace('CIK0000789019', 'CIK0001652044')
    if mutation == 'wrong_accession': research[0]['metrics']['operating_margin']['operands'][0] = research[0]['metrics']['operating_margin']['operands'][0].replace('0001193125-26-323660', '0001193125-26-000001')
    if mutation == 'nonfinite_margin': research[0]['metrics']['operating_margin']['value_percent'] = 'NaN'
    if mutation == 'inconsistent_label': matrix['themes'][0]['comparison_label'] = 'NO_MATCH_IN_RETRIEVED_PASSAGES'
    if mutation == 'historical_flag': matrix['historical_item1a_diff_performed'] = True
    if mutation == 'missing_research_anchor': research[0]['evidence']['risk'] = []; research[0]['evidence']['mda'] = []
    if mutation == 'wrong_revenue_tag': research[1]['metrics']['revenue_growth_yoy']['operands'][0] = research[1]['metrics']['revenue_growth_yoy']['operands'][0].replace('us-gaap:Revenues', 'us-gaap:CashAndCashEquivalentsAtCarryingValue')
    with pytest.raises(ResearchError):
        audit_evidence(plan, research, matrix, allowed=('MSFT','GOOGL'), budget=80000)


def test_rejects_unapproved_or_expanded_plan():
    plan, research, matrix = make_fixture()
    plan['companies'].append('TSLA')
    with pytest.raises(ResearchError):
        audit_evidence(plan, research, matrix, allowed=('MSFT','GOOGL'), budget=80000)


def test_rejects_model_hallucinated_passage_id():
    packet = audited(); invalid = json.loads(valid_model_output(packet))
    invalid['comparisons'][0]['citations'] = ['MSFT_2026-06-30_Item1A_99999']
    with pytest.raises(ResearchError): validate_synthesis(json.dumps(invalid), packet)


def test_rejects_model_missing_one_company_citation():
    packet = audited(); invalid = json.loads(valid_model_output(packet))
    invalid['comparisons'][0]['citations'] = invalid['comparisons'][0]['citations'][:1]
    with pytest.raises(ResearchError): validate_synthesis(json.dumps(invalid), packet)


def test_rejects_model_unsubstantiated_absence_or_materiality():
    packet = audited(); invalid = json.loads(valid_model_output(packet))
    invalid['comparisons'][0]['text'] = 'The second company has no risks disclosed in the filing.'
    with pytest.raises(ResearchError): validate_synthesis(json.dumps(invalid), packet)


class FakeCompletions:
    def __init__(self, responses): self.responses=responses; self.calls=[]
    def create(self, **kwargs):
        self.calls.append(kwargs)
        raw = self.responses[len(self.calls)-1]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])


def test_schema_retry_once_and_validates_all_citations():
    packet = audited(); completions = FakeCompletions(['{}', valid_model_output(packet)])
    synth = OpenRouterRiskSynthesizer(SimpleNamespace(model='openai/gpt-5-mini'),
                                     client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    result = synth(packet)
    assert len(completions.calls) == 2 and len(result['comparisons']) == 4
    assert 'previous output failed' in completions.calls[1]['messages'][-1]['content']
    assert '{}' not in completions.calls[1]['messages'][-1]['content']


def test_schema_bounded_to_two_calls_and_failure_closed():
    packet = audited(); completions = FakeCompletions(['{}','{}'])
    synth = OpenRouterRiskSynthesizer(SimpleNamespace(model='openai/gpt-5-mini'),
                                     client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    with pytest.raises(ResearchError, match='after one correction'):
        synth(packet)
    assert len(completions.calls) == 2


def test_no_evidence_theme_accepts_empty_citations_but_not_absence_claim():
    packet = audited()
    packet['risk_evidence']['cyber_privacy'] = {'MSFT': [], 'GOOGL': []}
    val = json.loads(valid_model_output(audited()))
    val['comparisons'][0]['citations'] = []
    val['comparisons'][0]['text'] = 'The retrieved evidence is insufficient for a supported cybersecurity comparison.'
    result = validate_synthesis(json.dumps(val), packet)
    assert result['comparisons'][0]['citations'] == []


def test_langgraph_supervisor_no_llm_gate_and_audit():
    pytest.importorskip('langgraph')
    plan, research, matrix = make_fixture()
    g = build_supervisor_graph(allowed=('MSFT','GOOGL'), budget=80000)
    final = g.invoke({'plan': plan, 'approved': True, 'research_results': research, 'risk_matrix': matrix})
    assert final['status'] == 'SUPERVISOR_EVIDENCE_READY'
    assert final['audited']['publication_performed'] is False
    with pytest.raises(ResearchError):
        g.invoke({'plan': plan, 'approved': False, 'research_results': research, 'risk_matrix': matrix})


def test_langgraph_supervisor_with_mocked_validated_synthesizer():
    pytest.importorskip('langgraph')
    plan, research, matrix = make_fixture()
    g = build_supervisor_graph(allowed=('MSFT','GOOGL'), budget=80000,
                 synthesizer=lambda packet: validate_synthesis(valid_model_output(packet), packet))
    final = g.invoke({'plan': plan, 'approved': True, 'research_results': research, 'risk_matrix': matrix})
    assert final['status'] == 'GROUNDED_SYNTHESIS_READY'
    assert len(final['synthesized']['comparisons']) == 4

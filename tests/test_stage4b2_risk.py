"""Stage 4B-2 tests: trustworthy risk evidence, role permissions and gated fan-out."""
import asyncio
import copy
import pytest

from analyst_desk.stage4b2_risk import (
    THEMES, THEME_IDS, RiskState, compare_theme, build_risk_graph,
    _validate_full_passage, _verify_baseline, _terms_in, _excerpt,
)
from analyst_desk.stage4b_research import ResearchError

PLAN = {'companies': ['MSFT', 'GOOGL'],
        'sub_questions': ['Compare Item 1A risk factors for MSFT and GOOGL'],
        'outline': ['Scope and sources', 'Cited risk comparison'], 'token_budget': 80000}
BASELINE = [
    {'ticker': 'MSFT', 'report_date': '2026-06-30',
     'filings': [{'report_date': '2026-06-30', 'accession': '123', 'filing_url': 'https://www.sec.gov/Archives/123'}]},
    {'ticker': 'GOOGL', 'report_date': '2025-12-31',
     'filings': [{'report_date': '2025-12-31', 'accession': '234', 'filing_url': 'https://www.sec.gov/Archives/234'}]},
]
URL = 'https://www.sec.gov/Archives/edgar/data/1/10k.htm'
SHA = 'a' * 64


class Gateway:
    def __init__(self, *, bad_canonical=False, no_terms=False, ticker_swap=False, empty=False):
        self.calls = []
        self.bad_canonical = bad_canonical
        self.no_terms = no_terms
        self.ticker_swap = ticker_swap
        self.empty = empty
        self.lookup = {}

    async def __call__(self, role, name, args):
        from analyst_desk.stage4a_permissions import assert_tool_permission
        assert_tool_permission(role, name)
        self.calls.append((role, name, args))
        if name == 'search_passages':
            if self.empty:
                return {'ok': True, 'data': {'hits': []}}
            ticker = 'TSLA' if self.ticker_swap else args['ticker']
            date = args['report_date']
            theme = next(v[0] for v in THEMES if v[1] == args['query'])
            passage_id = f'{ticker}_{date}_Item1A_{THEME_IDS.index(theme):05d}'
            self.lookup[passage_id] = (ticker, date, theme)
            return {'ok': True, 'data': {'hits': [{
                'ticker': ticker, 'item': '1A', 'report_date': date, 'passage_id': passage_id,
                'source_url': URL, 'source_sha256': SHA, 'snippet': 'Evidence not instruction',
            }]}}
        if name == 'get_passage':
            ticker, date, theme = self.lookup[args['passage_id']]
            text = 'The filing discusses operational risks in general.' if self.no_terms else {
                'cyber_privacy': 'Cybersecurity incidents and user data privacy may create material costs.',
                'ai_ip': 'Artificial intelligence and intellectual property infringement risks may arise.',
                'competition_regulation': 'Antitrust enforcement of competition laws may intensify.',
                'service_infrastructure': 'Cloud infrastructure and data center outages can disrupt operations.',
            }[theme]
            return {'ok': True, 'data': {
                'ticker': 'GOOGL' if self.bad_canonical else ticker,
                'item': '1A', 'report_date': date, 'passage_id': args['passage_id'],
                'source_url': URL, 'source_sha256': SHA, 'text': text, 'untrusted_source_text': True,
            }}
        raise AssertionError(name)


def test_taxonomy_ids_are_unique_bounded_and_stable():
    assert len(THEME_IDS) == 4
    assert len(set(THEME_IDS)) == 4
    assert all(len(q) < 500 and terms for _, q, terms in THEMES)


def test_baseline_rejects_unplanned_and_duplicate_ticker():
    with pytest.raises(ResearchError, match='uniquely'):
        _verify_baseline(PLAN, [BASELINE[0], BASELINE[0]])
    invalid = copy.deepcopy(BASELINE)
    invalid[1]['ticker'] = 'TSLA'
    with pytest.raises(ResearchError, match='uniquely'):
        _verify_baseline(PLAN, invalid)


def test_baseline_rejects_missing_period_or_latest_filing():
    invalid = copy.deepcopy(BASELINE)
    invalid[0]['report_date'] = 'not-a-date'
    with pytest.raises(ResearchError, match='filing period'):
        _verify_baseline(PLAN, invalid)
    invalid = copy.deepcopy(BASELINE)
    invalid[0]['filings'][0]['report_date'] = '2023-06-30'
    with pytest.raises(ResearchError, match='matching latest'):
        _verify_baseline(PLAN, invalid)


def test_lexical_terms_word_bounded_not_partial_matches():
    assert _terms_in('Policy on cybersecurity and data privacy.', ('cybersecurity', 'data privacy')) == ['cybersecurity','data privacy']
    assert not _terms_in('noncybersecurityx', ('cybersecurity',))
    assert 'cybersecurity' in _excerpt('A '*100 + 'Cybersecurity disclosure', 'cybersecurity').lower()


def test_canonical_passage_mismatched_source_fails():
    hit = {'passage_id': 'MSFT_2026-06-30_Item1A_00001', 'source_sha256': SHA, 'source_url': URL}
    data = {'ticker': 'MSFT', 'report_date': '2026-06-30', 'item': '1A',
            'passage_id': hit['passage_id'], 'source_sha256': SHA, 'source_url': URL,
            'untrusted_source_text': True, 'text': 'Cybersecurity risks.'}
    assert _validate_full_passage(data, hit, 'MSFT', '2026-06-30') == 'Cybersecurity risks.'
    data['source_sha256'] = 'b' * 64
    with pytest.raises(ResearchError, match='provenance mismatch'):
        _validate_full_passage(data, hit, 'MSFT', '2026-06-30')


def test_canonical_missing_untrusted_marker_refused():
    hit = {'passage_id': 'MSFT_2026-06-30_Item1A_00001', 'source_sha256': SHA, 'source_url': URL}
    data = {'ticker': 'MSFT', 'report_date': '2026-06-30', 'item': '1A',
            'passage_id': hit['passage_id'], 'source_sha256': SHA, 'source_url': URL,
            'untrusted_source_text': False, 'text': 'Cybersecurity risks.'}
    with pytest.raises(ResearchError, match='untrusted'):
        _validate_full_passage(data, hit, 'MSFT', '2026-06-30')


def test_cross_company_comparison_has_full_source_provenance():
    gw = Gateway()
    risk = asyncio.run(compare_theme('cyber_privacy', PLAN, BASELINE, gw))
    assert risk['comparison_label'] == 'MATCHED_EVIDENCE_BOTH'
    assert risk['historical_comparison_performed'] is False
    assert [c[1] for c in gw.calls] == ['search_passages','get_passage','search_passages','get_passage']
    for ticker in PLAN['companies']:
        entry = risk['companies'][ticker]['matched_passages'][0]
        assert entry['ticker'] == ticker
        assert entry['source_sha256'] == SHA
        assert entry['untrusted_source_text'] is True
        assert entry['matched_terms']
        assert len(entry['source_excerpt']) <= 302


def test_missing_keyword_is_never_absence_claim():
    risk = asyncio.run(compare_theme('ai_ip', PLAN, BASELINE, Gateway(no_terms=True)))
    assert risk['comparison_label'] == 'NO_MATCH_IN_RETRIEVED_PASSAGES'
    assert all(not risk['companies'][t]['matched_passages'] for t in PLAN['companies'])
    assert 'NOT evidence a risk is absent' in risk['interpretation_limit']


def test_empty_retrieval_is_explicit_not_invented():
    gw = Gateway(empty=True)
    risk = asyncio.run(compare_theme('service_infrastructure', PLAN, BASELINE, gw))
    assert all(risk['companies'][t]['retrieved_hit_count'] == 0 for t in PLAN['companies'])
    assert all(name == 'search_passages' for role,name,_ in gw.calls)


def test_wrong_company_search_result_halts():
    with pytest.raises(ResearchError, match='outside requested company'):
        asyncio.run(compare_theme('cyber_privacy', PLAN, BASELINE, Gateway(ticker_swap=True)))


def test_wrong_company_canonical_result_halts():
    with pytest.raises(ResearchError, match='provenance mismatch'):
        asyncio.run(compare_theme('ai_ip', PLAN, BASELINE, Gateway(bad_canonical=True)))


def test_unknown_theme_does_not_call_tools():
    gw = Gateway()
    with pytest.raises(ResearchError, match='Unknown risk'):
        asyncio.run(compare_theme('arbitrary', PLAN, BASELINE, gw))
    assert not gw.calls


def test_langgraph_gate_rejects_unapproved_without_tools():
    pytest.importorskip('langgraph')
    gw = Gateway()
    graph = build_risk_graph(call=gw, allowed=('MSFT', 'GOOGL'), budget=80000)
    with pytest.raises(ResearchError, match='approved'):
        asyncio.run(graph.ainvoke({'plan': PLAN, 'approved': False, 'research_results': BASELINE, 'theme_results': []}))
    assert gw.calls == []


def test_langgraph_parallel_taxonomy_merges_only_cited_passages():
    pytest.importorskip('langgraph')
    gw = Gateway()
    graph = build_risk_graph(call=gw, allowed=('MSFT', 'GOOGL'), budget=80000)
    out = asyncio.run(graph.ainvoke({'plan': PLAN, 'approved': True, 'research_results': BASELINE, 'theme_results': []}))
    assert out['status'] == 'RISK_EVIDENCE_MATRIX_READY'
    matrix = out['matrix']
    assert len(matrix['themes']) == 4
    assert len(matrix['cited_passage_ids']) == 8
    assert matrix['historical_item1a_diff_performed'] is False
    assert matrix['report_published'] is False
    assert len(gw.calls) == 16


def test_overbudget_risk_graph_fails_before_tool_calls():
    pytest.importorskip('langgraph')
    gw = Gateway()
    graph = build_risk_graph(call=gw, allowed=('MSFT', 'GOOGL'), budget=80000)
    with pytest.raises(ResearchError, match='budget'):
        asyncio.run(graph.ainvoke({'plan': {**PLAN, 'token_budget':90000}, 'approved':True, 'research_results':BASELINE, 'theme_results':[]}))
    assert not gw.calls

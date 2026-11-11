"""Stage 4B read-only orchestration contracts; no SEC network or LLM calls."""
import asyncio

import pytest

from analyst_desk.stage4b_research import (
    ResearchError, _hits, _metric, _filings, check_approved_plan, research_company, build_research_graph,
)
from analyst_desk.stage4a_permissions import ToolPermissionError, assert_tool_permission

PLAN = {'companies': ['MSFT', 'GOOGL'],
        'sub_questions': ['Compare disclosed material risk factors across MSFT and GOOGL.'],
        'outline': ['Scope', 'Source-backed findings'], 'token_budget': 80000}


def filing(ticker, date):
    return {'ticker': ticker, 'report_date': date,
            'accession': '0000000001-26-000111', 'filing_url': 'https://www.sec.gov/Archives/edgar/data/1/report.htm'}


class FakeGateway:
    def __init__(self, *, no_margin=False, no_hit=False):
        self.calls = []
        self.no_margin = no_margin
        self.no_hit = no_hit

    async def __call__(self, role, name, args):
        assert_tool_permission(role, name)
        self.calls.append((role, name, args))
        ticker = args['ticker']
        if name == 'list_annual_filings':
            return {'ok': True, 'data': {'filings': [filing(ticker, '2026-06-30'), filing(ticker, '2025-06-30')]}}
        if name == 'search_passages':
            if self.no_hit:
                return {'ok': True, 'data': {'hits': []}}
            return {'ok': True, 'data': {'hits': [{
                'ticker': ticker, 'item': args['item'], 'passage_id': f'{ticker}_2026-06-30_Item{args["item"]}_00011',
                'source_url': 'https://www.sec.gov/Archives/edgar/data/1/report.htm',
                'report_date': '2026-06-30', 'source_sha256': 'a' * 64,
                'snippet': 'Untrusted financial reporting evidence. ' * 50,
            }]}}
        if name == 'calculate_operating_margin' and self.no_margin:
            return {'ok': False, 'error_code': 'FACT_UNAVAILABLE'}
        if name in {'calculate_operating_margin', 'calculate_revenue_growth'}:
            return {'ok': True, 'data': {
                'name': 'operating_margin' if name == 'calculate_operating_margin' else 'revenue_growth_yoy',
                'ticker': ticker, 'report_date': args.get('report_date'), 'current_report_date': args.get('current_report_date'),
                'value_percent': '12.34', 'operands': ['CIK|us-gaap:Revenues|USD'],
                'source_verified_by': 'EDGAR_SHA256_URL_SIDECARS'}}
        raise AssertionError(name)


def test_unapproved_plan_never_reaches_tools():
    with pytest.raises(ResearchError, match='approved'):
        check_approved_plan(PLAN, approved=False, allowed=('MSFT', 'GOOGL'), budget=80000)


def test_scope_escalation_rejected():
    with pytest.raises(ResearchError, match='unrequested'):
        check_approved_plan({**PLAN, 'companies': ['MSFT', 'TSLA']}, approved=True,
                            allowed=('MSFT', 'GOOGL'), budget=80000)


def test_overbudget_rejected():
    with pytest.raises(ResearchError, match='budget'):
        check_approved_plan({**PLAN, 'token_budget': 99999}, approved=True,
                            allowed=('MSFT', 'GOOGL'), budget=80000)


def test_company_dispatch_rejects_unplanned_ticker():
    gateway = FakeGateway()
    with pytest.raises(ResearchError, match='absent'):
        asyncio.run(research_company('TSLA', PLAN, gateway))
    assert gateway.calls == []


def test_role_permissions_still_enforced():
    with pytest.raises(ToolPermissionError):
        assert_tool_permission('risk_diff', 'publish_report')
    with pytest.raises(ToolPermissionError):
        assert_tool_permission('quant', 'create_report_draft')


def test_one_company_has_citations_and_fact_ids():
    gw = FakeGateway()
    result = asyncio.run(research_company('MSFT', PLAN, gw))
    assert result['ticker'] == 'MSFT'
    assert result['metrics']['operating_margin']['value_percent'] == '12.34'
    assert result['metrics']['revenue_growth_yoy']['prior_report_date'] == '2025-06-30'
    assert result['evidence']['risk'][0]['item'] == '1A'
    assert result['evidence']['mda'][0]['item'] == '7'
    assert result['evidence']['risk'][0]['untrusted_source_text'] is True
    assert len(result['evidence']['risk'][0]['snippet']) <= 360
    assert result['historical_item1a_comparison_performed'] is False
    assert len(gw.calls) == 5
    assert [x[1] for x in gw.calls] == [
        'list_annual_filings', 'search_passages', 'search_passages',
        'calculate_operating_margin', 'calculate_revenue_growth']


def test_missing_calculation_is_explicit_not_faked():
    out = asyncio.run(research_company('MSFT', PLAN, FakeGateway(no_margin=True)))
    assert 'operating_margin' not in out['metrics']
    assert 'OPERATING_MARGIN_UNAVAILABLE:FACT_UNAVAILABLE' in out['warnings']


def test_missing_corpus_results_not_faked():
    out = asyncio.run(research_company('MSFT', PLAN, FakeGateway(no_hit=True)))
    assert not out['evidence']['risk']
    assert 'NO_1A_PASSAGES_FOR_2026-06-30' in out['warnings']


def test_search_wrong_company_is_integrity_error():
    with pytest.raises(ResearchError, match='outside'):
        _hits({'hits': [{'ticker': 'GOOGL', 'item': '1A'}]}, 'MSFT', '1A')


def test_retrieval_url_not_sec_is_integrity_error():
    with pytest.raises(ResearchError, match='SEC'):
        _hits({'hits': [{'ticker': 'MSFT', 'item': '1A', 'passage_id': 'MSFT_2026_001', 'source_url': 'http://evil.test', 'source_sha256': 'a'*64}]}, 'MSFT', '1A')


def test_xbrl_operand_ids_required():
    with pytest.raises(ResearchError, match='XBRL'):
        _metric({'name': 'operating_margin', 'ticker': 'MSFT', 'report_date': '2026-06-30', 'value_percent': '12.34', 'operands': ['not-a-fact'], 'source_verified_by': 'EDGAR_SHA256_URL_SIDECARS'}, 'MSFT', '2026-06-30', 'operating_margin')


def test_wrong_company_edgar_filings_rejected():
    with pytest.raises(ResearchError, match='wrong-company'):
        _filings({'filings': [filing('GOOGL', '2025-12-31')]}, 'MSFT')


def test_real_langgraph_parallel_send_with_mocked_mcp():
    pytest.importorskip('langgraph')
    gateway = FakeGateway()
    graph = build_research_graph(call=gateway, allowed=('MSFT','GOOGL'), budget=80000)
    result = asyncio.run(graph.ainvoke({'plan': PLAN, 'approved': True, 'research_results': []}))
    assert result['status'] == 'RESEARCH_EVIDENCE_READY'
    assert [c['ticker'] for c in result['research_results']] == ['MSFT', 'GOOGL']
    assert result['summary']['publication_performed'] is False
    assert len(result['summary']['citations']) == 4
    assert len(result['summary']['xbrl_fact_ids']) == 1
    assert len(gateway.calls) == 10


def test_langgraph_gate_blocks_before_any_mcp():
    pytest.importorskip('langgraph')
    gw = FakeGateway()
    graph = build_research_graph(call=gw, allowed=('MSFT','GOOGL'), budget=80000)
    with pytest.raises(ResearchError, match='approved'):
        asyncio.run(graph.ainvoke({'plan': PLAN, 'approved': False, 'research_results': []}))
    assert gw.calls == []


def test_search_rejects_other_fiscal_year():
    with pytest.raises(ResearchError, match='period'):
        _hits({'hits': [{'ticker': 'MSFT', 'item': '1A', 'passage_id': 'MSFT_2025_001',
                         'source_url': 'https://www.sec.gov/Archives/test.htm', 'source_sha256': 'a'*64,
                         'report_date': '2025-06-30'}]}, 'MSFT', '1A', report_date='2026-06-30')

def test_search_rejects_missing_source_checksum():
    with pytest.raises(ResearchError, match='checksum'):
        _hits({'hits': [{'ticker': 'MSFT', 'item': '1A', 'passage_id': 'MSFT_2026_001',
                         'source_url': 'https://www.sec.gov/Archives/test.htm', 'source_sha256': None}]}, 'MSFT', '1A')


def test_calc_rejects_wrong_company_and_date():
    metric = {'name': 'operating_margin', 'ticker': 'GOOGL', 'report_date': '2026-06-30',
              'value_percent': '12.34', 'operands': ['CIK|us-gaap:Revenues|USD'],
              'source_verified_by': 'EDGAR_SHA256_URL_SIDECARS'}
    with pytest.raises(ResearchError, match='wrong company'):
        _metric(metric, 'MSFT', '2026-06-30', 'operating_margin')
    metric['ticker'] = 'MSFT'
    with pytest.raises(ResearchError, match='mismatched fiscal period'):
        _metric(metric, 'MSFT', '2025-06-30', 'operating_margin')

def test_calc_rejects_nonfinite_percentage():
    metric = {'name': 'operating_margin', 'ticker': 'MSFT', 'report_date': '2026-06-30',
              'value_percent': 'NaN', 'operands': ['CIK|us-gaap:Revenues|USD'],
              'source_verified_by': 'EDGAR_SHA256_URL_SIDECARS'}
    with pytest.raises(ResearchError, match='nonfinite'):
        _metric(metric, 'MSFT', '2026-06-30', 'operating_margin')

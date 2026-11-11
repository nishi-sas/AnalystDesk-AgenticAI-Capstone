from phase10_ui_helpers import (
    FOCUS_OPTIONS, SUPPORTED_TICKERS, compose_research_request,
    extract_financial_rows, financial_table, workflow_mermaid,
)
import pytest


def test_verified_cohort_is_twelve_unique_companies():
    assert len(SUPPORTED_TICKERS) == 12
    assert len(set(SUPPORTED_TICKERS)) == 12
    assert {'TGT','HD','MSFT','GOOGL'}.issubset(SUPPORTED_TICKERS)


def test_free_text_question_is_restricted_to_selected_pair():
    request = compose_research_request('Compare risk disclosures.', 'TGT', 'HD', FOCUS_OPTIONS[0])
    assert 'Compare TGT and HD' in request
    assert 'Compare risk disclosures.' in request
    assert 'cite supporting evidence' in request


def test_reject_duplicate_company():
    with pytest.raises(ValueError):
        compose_research_request('Compare', 'TGT', 'TGT', FOCUS_OPTIONS[0])


def test_reject_unlisted_ticker():
    with pytest.raises(ValueError):
        compose_research_request('Compare', 'NOT_A_REAL_TICKER', 'HD', FOCUS_OPTIONS[0])


def test_extract_only_real_financial_rows():
    draft = '| TGT | 2026-01-31 | 4.88% | -1.68% | VERIFIED_SAME_TAG |\n| HD | 2026-02-01 | 12.68% | 3.24% | VERIFIED_SAME_TAG |'
    rows = extract_financial_rows(draft, ('TGT','HD'))
    assert [(r.ticker,r.operating_margin,r.revenue_growth_yoy) for r in rows] == [
        ('TGT',4.88,-1.68),('HD',12.68,3.24)
    ]
    assert '4.88%' in financial_table(rows)
    assert '-1.68%' in financial_table(rows)


def test_no_financial_rows_invented_when_absent():
    assert extract_financial_rows('This is a narrative-only report', ('TGT','HD')) == []


def test_workflow_is_explicitly_human_gated():
    diagram = workflow_mermaid()
    assert 'Human approval' in diagram
    assert 'Independent Critic' in diagram

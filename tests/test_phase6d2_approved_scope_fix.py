"""Regression tests for Phase 6D2's approved 12-company input scope."""
import pytest
from analyst_desk.phase6d2_financial_integrity import (
    ROW, HEADING, VERIFIED_COMPANIES, parse_draft_financials,
)
from analyst_desk.stage4b_research import ResearchError


def test_verified_company_coverage_is_explicit():
    assert VERIFIED_COMPANIES == {
        'MSFT', 'GOOGL', 'AAPL', 'META', 'ADBE', 'CRM',
        'TGT', 'HD', 'LOW', 'BBY', 'DG', 'ULTA',
    }


def test_financial_row_and_operand_headings_accept_verified_new_tickers():
    assert ROW.fullmatch('| TGT | 2026-01-31 | 4.88% | -1.68% | VERIFIED_SAME_TAG |')
    assert ROW.fullmatch('| HD | 2026-02-01 | 12.68% | 3.24% | VERIFIED_SAME_TAG |')
    assert HEADING.fullmatch('TGT — operating_margin (VERIFIED_SAME_PERIOD):')
    assert HEADING.fullmatch('HD — revenue_growth_yoy (VERIFIED_SAME_TAG):')


def test_unapproved_scope_rejected_before_parsing():
    for companies in (('TSLA',), ('TGT', 'TSLA'), ('TGT', 'TGT'), ('HD', 'hd')):
        with pytest.raises(ResearchError, match='UNSUPPORTED_COMPANY_SCOPE'):
            parse_draft_financials('# placeholder', companies)


def test_original_companies_are_still_accepted_by_scope_guard():
    # No financial table means another validation error, not an unsupported ticker.
    with pytest.raises(ResearchError) as exc:
        parse_draft_financials('# placeholder', ('MSFT', 'GOOGL'))
    assert 'UNSUPPORTED_COMPANY_SCOPE' not in str(exc.value)

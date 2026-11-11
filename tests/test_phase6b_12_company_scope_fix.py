"""Focused smoke tests for the Stage 4C-4 registration ticker-scope correction."""

from analyst_desk.phase6b_output import _FINANCIAL_ROW, _SUPPORTED_CIK_PREFIXES


def test_verified_cohort_has_unique_issuer_ids():
    expected = {'AAPL', 'ADBE', 'BBY', 'CRM', 'DG', 'GOOGL', 'HD', 'LOW', 'META', 'MSFT', 'TGT', 'ULTA'}
    assert set(_SUPPORTED_CIK_PREFIXES) == expected
    assert len(set(_SUPPORTED_CIK_PREFIXES.values())) == 12
    assert all(v.startswith('CIK') and v.endswith('|') and len(v) == 14 for v in _SUPPORTED_CIK_PREFIXES.values())


def test_old_and_expanded_issuer_matches():
    assert _SUPPORTED_CIK_PREFIXES['MSFT'] == 'CIK0000789019|'
    assert _SUPPORTED_CIK_PREFIXES['GOOGL'] == 'CIK0001652044|'
    assert _SUPPORTED_CIK_PREFIXES['TGT'] == 'CIK0000027419|'
    assert _SUPPORTED_CIK_PREFIXES['HD'] == 'CIK0000354950|'


def test_expanded_companies_financial_rows_are_detected():
    for company, date, margin, growth in (
        ('TGT', '2026-01-31', '4.88', '-1.68'),
        ('HD', '2026-02-01', '12.68', '3.24'),
        ('MSFT', '2026-06-30', '45.33', '12.00'),
    ):
        text = f'| {company} | {date} | {margin}% | {growth}% | VERIFIED_SAME_TAG |'
        found = list(_FINANCIAL_ROW.finditer(text))
        assert len(found) == 1 and found[0].group(1) == company, (company, found)


def test_unrecognized_ticker_has_no_issuer_mapping():
    assert _SUPPORTED_CIK_PREFIXES.get('FAKE') is None

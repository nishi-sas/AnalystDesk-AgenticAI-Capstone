"""Focused checks that financial-row detection and fixed SEC CIK mapping agree."""
from analyst_desk.phase6b_output import _FINANCIAL_ROW, _SUPPORTED_CIK_PREFIXES


def test_tgt_hd_and_original_issuer_mapping():
    assert _SUPPORTED_CIK_PREFIXES['TGT'] == 'CIK0000027419|'
    assert _SUPPORTED_CIK_PREFIXES['HD'] == 'CIK0000354950|'
    assert _SUPPORTED_CIK_PREFIXES['MSFT'] == 'CIK0000789019|'
    assert _SUPPORTED_CIK_PREFIXES['GOOGL'] == 'CIK0001652044|'
    assert len(_SUPPORTED_CIK_PREFIXES) == 12
    assert len(set(_SUPPORTED_CIK_PREFIXES.values())) == 12
    assert _SUPPORTED_CIK_PREFIXES.get('FAKE') is None


def test_expanded_financial_rows_detected():
    # If the regex was already generic, this succeeds without modifying it.
    # If not, fail safely rather than leaving uncovered financial claims.
    for ticker, end, margin, growth in [
        ('TGT', '2026-01-31', '4.88', '-1.68'),
        ('HD', '2026-02-01', '12.68', '3.24'),
        ('MSFT', '2026-06-30', '45.33', '12.00'),
    ]:
        row = f'| {ticker} | {end} | {margin}% | {growth}% | VERIFIED_SAME_TAG |'
        found = list(_FINANCIAL_ROW.finditer(row))
        assert len(found) == 1 and found[0].group(1) == ticker, ticker

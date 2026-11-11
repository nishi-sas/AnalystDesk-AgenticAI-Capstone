"""Verify the isolated staging root is the cwd during each SEC parse.

Offline tests: neither the SEC nor a real filing parser is called.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import pytest

from tools import build_verified_coverage as m


def _doc(ticker: str, year: int) -> dict:
    acc = f'{year:018d}'
    return {
        'ticker': ticker, 'report_date': f'{year}-12-31', 'accession': acc,
        'local_path': f'data/edgar_cache/documents/CIK0000000001/{acc}/{ticker.lower()}.htm',
    }


def _returns(ticker: str, row: dict):
    date = row['report_date']
    passages = [
        {'ticker': ticker, 'report_date': date, 'item': item,
         'passage_id': f'{ticker}_{date}_Item{item}_001', 'text': 'SEC disclosure ' * 25,
         'accession': row['accession'],
         'source_url': 'https://www.sec.gov/Archives/edgar/data/1/filing.htm'}
        for item in ('1A', '7', '8')
    ]
    summary = {'ticker': ticker, 'report_date': date, 'passage_count': 3,
               'sections': {item: {'characters': 500, 'tables': 0} for item in ('1A', '7', '8')}}
    return passages, [summary]


def test_relative_manifest_paths_resolve_within_staging_cache(tmp_path, monkeypatch):
    stage = tmp_path / 'isolated'
    docs = [_doc('AAPL', year) for year in (2025, 2024, 2023)]
    for doc in docs:
        path = stage / doc['local_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test filing content' * 100)

    call_dates = []
    original_cwd = Path.cwd()

    def fake_process_manifest(manifest_path, *, cache_root, max_chars):
        # Simulate the existing parser's cwd-relative manifest path security check.
        assert Path.cwd() == stage.resolve()
        assert Path(cache_root).resolve() == (stage / 'data/edgar_cache').resolve()
        assert max_chars == 2400
        single = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        assert len(single) == 1
        row = single[0]
        resolved = Path(row['local_path']).resolve()
        assert resolved.is_relative_to(Path(cache_root).resolve())
        assert resolved.is_file()
        call_dates.append(row['report_date'])
        return _returns('AAPL', row)

    import analyst_desk.document_parsing as doc_parser
    monkeypatch.setattr(doc_parser, 'process_manifest', fake_process_manifest)
    passages, summaries, verified = m.parse_and_validate('AAPL', docs, stage)
    assert Path.cwd() == original_cwd
    assert len(call_dates) == len(passages) // 3 == len(summaries) == 3
    assert verified['status'] == 'PARSER_VALIDATED'


def test_cwd_restored_and_failure_keeps_exact_filing_date(tmp_path, monkeypatch):
    stage = tmp_path / 'isolated'
    stage.mkdir()
    docs = [_doc('ORCL', year) for year in (2025, 2024, 2023)]
    import analyst_desk.document_parsing as doc_parser
    original_cwd = Path.cwd()

    def fake_fail(*args, **kwargs):
        assert Path.cwd() == stage.resolve()
        raise ValueError('Missing or empty Item 8')

    monkeypatch.setattr(doc_parser, 'process_manifest', fake_fail)
    with pytest.raises(m.CoverageError, match='ORCL 2025-12-31 failed extraction: Missing or empty Item 8'):
        m.parse_and_validate('ORCL', docs, stage)
    assert Path.cwd() == original_cwd

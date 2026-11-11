"""Offline SEC historical pagination regression tests; no SEC network calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analyst_desk.sec_client import EdgarClient, EdgarError

CIK = 1326801
NAME = f"CIK{CIK:010d}-submissions-001.json"


def table(*rows):
    columns = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument")
    return {key: [row[i] for row in rows] for i, key in enumerate(columns)}


def row(year, *, form='10-K', accession=None, filing_date=None):
    return (form, accession or f'0001326801-{str(year)[-2:]}-000001',
            filing_date or f'{year+1}-02-15', f'{year}-12-31', f'meta-{year}.htm')


def client(tmp_path, monkeypatch, recent_rows, historical_rows=(), pages=True):
    sec = EdgarClient(cache_dir=tmp_path, offline=True)
    monkeypatch.setattr(sec, 'ticker_to_cik', lambda ticker: (CIK, 'Meta Platforms, Inc.'))
    monkeypatch.setattr(sec, 'submissions', lambda cik: {'name': 'Meta Platforms, Inc.',
        'filings': {'recent': table(*recent_rows), 'files':
                   [{'name': NAME, 'filingTo': '2024-01-01'}] if pages else []}})
    if historical_rows:
        path = tmp_path / 'submissions' / NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(table(*historical_rows)), encoding='utf-8')
    return sec


def test_recent_only_does_not_fetch_historical_pages(tmp_path, monkeypatch):
    sec = client(tmp_path, monkeypatch, [row(2025), row(2024), row(2023)])
    filings = sec.annual_filings('META', years=3)
    assert [x.report_date for x in filings] == ['2025-12-31', '2024-12-31', '2023-12-31']
    assert not (tmp_path / 'submissions' / NAME).exists()


def test_historical_cache_fills_missing_year_without_network(tmp_path, monkeypatch):
    sec = client(tmp_path, monkeypatch, [row(2025), row(2024)], [row(2023), row(2022)])
    filings = sec.annual_filings('META', years=3)
    assert [x.report_date for x in filings] == ['2025-12-31', '2024-12-31', '2023-12-31']
    assert all(x.ticker == 'META' for x in filings)


def test_historical_amendments_and_duplicate_years_not_counted(tmp_path, monkeypatch):
    sec = client(tmp_path, monkeypatch, [row(2025), row(2024)],
                 [row(2024, accession='0001326801-25-000002'),
                  row(2023, form='10-K/A'), row(2022)])
    filings = sec.annual_filings('META', years=3)
    assert [x.report_date for x in filings] == ['2025-12-31', '2024-12-31', '2022-12-31']


def test_offline_missing_page_fails_closed(tmp_path, monkeypatch):
    sec = client(tmp_path, monkeypatch, [row(2025), row(2024)])
    with pytest.raises(EdgarError, match='Offline cache miss'):
        sec.annual_filings('META', years=3)


def test_all_pages_insufficient_fails_closed(tmp_path, monkeypatch):
    sec = client(tmp_path, monkeypatch, [row(2025), row(2024)],
                 [row(2024, accession='0001326801-25-000002')])
    with pytest.raises(EdgarError, match='Only 2 usable 10-K fiscal years'):
        sec.annual_filings('META', years=3)


def test_invalid_historical_filename_blocked(tmp_path, monkeypatch):
    sec = client(tmp_path, monkeypatch, [row(2025), row(2024)])
    monkeypatch.setattr(sec, 'submissions', lambda cik: {'name': 'Meta',
        'filings': {'recent': table(row(2025), row(2024)),
                    'files': [{'name': '../secret.json', 'filingTo': '2024-01-01'}]}})
    with pytest.raises(EdgarError, match='Invalid SEC historical submissions filename'):
        sec.annual_filings('META', years=3)


def test_requires_positive_year_count(tmp_path):
    sec = EdgarClient(cache_dir=tmp_path, offline=True)
    with pytest.raises(EdgarError, match='positive integer'):
        sec.annual_filings('META', years=0)

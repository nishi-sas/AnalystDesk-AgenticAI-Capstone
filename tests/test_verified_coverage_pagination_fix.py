"""Pure offline regression tests for text integrity and page-marker filtering.

No SEC requests, no model loading, no original project files mutated.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
import types

import pytest

from tools import build_verified_coverage as c


def record(year):
    return {'ticker': 'GOOGL', 'report_date': f'{year}-12-31',
            'accession': f'{year:018d}',
            'local_path': f'data/edgar_cache/documents/CIK0001652044/{year:018d}/goog-{year}.htm'}


def valid_output(d, *, marker='44.', is_table=False, section='8', invalid_text=None):
    rows = []
    for item in ('1A', '7', '8'):
        rows.append({'ticker': 'GOOGL', 'report_date': d['report_date'],
                     'item': item, 'passage_id': f"GOOGL_{d['report_date']}_Item{item}_00001",
                     'text': 'Real financial or narrative content ' * 20,
                     'is_table': False,
                     'source_url': 'https://www.sec.gov/Archives/edgar/data/1652044/example.htm',
                     'accession': d['accession']})
    if marker is not None:
        rows.append({'ticker': 'GOOGL', 'report_date': d['report_date'],
                     'item': section,
                     'passage_id': f"GOOGL_{d['report_date']}_Item{section}_00002",
                     'text': invalid_text if invalid_text is not None else marker,
                     'is_table': is_table,
                     'source_url': 'https://www.sec.gov/Archives/edgar/data/1652044/example.htm',
                     'accession': d['accession']})
    summary = {'ticker': 'GOOGL', 'report_date': d['report_date'],
               'sections': {k: {'characters': 1500, 'tables': 1 if k == '8' else 0}
                            for k in ('1A', '7', '8')}, 'passage_count': len(rows)}
    return rows, [summary]


def fake_parser(monkeypatch, output_for):
    def process_manifest(path, *, cache_root, max_chars):
        docs = json.loads(Path(path).read_text(encoding='utf-8'))
        assert len(docs) == 1 and max_chars == 2400
        return output_for(docs[0])
    pkg = types.ModuleType('analyst_desk')
    mod = types.ModuleType('analyst_desk.document_parsing')
    mod.process_manifest = process_manifest
    monkeypatch.setitem(sys.modules, 'analyst_desk', pkg)
    monkeypatch.setitem(sys.modules, 'analyst_desk.document_parsing', mod)


def test_only_item8_non_table_paginated_label_is_recognized():
    good = {'item':'8','is_table':False,'text':'44.'}
    assert c.standalone_item8_page_number(good)
    assert c.standalone_item8_page_number({**good, 'text':' 87. '})
    assert not c.standalone_item8_page_number({**good,'item':'1A'})
    assert not c.standalone_item8_page_number({**good,'is_table':True})
    assert not c.standalone_item8_page_number({**good,'text':'44'})
    assert not c.standalone_item8_page_number({**good,'text':'44. Revenue'})
    assert not c.standalone_item8_page_number({**good,'text':'\ufffd44.'})
    assert not c.standalone_item8_page_number({**good,'text':'0.'})
    assert not c.standalone_item8_page_number({**good,'text':'1000.'})


def test_36_filings_still_require_three_periods(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    fake_parser(monkeypatch, lambda d: valid_output(d))
    paragraphs, summaries, verdict = c.parse_and_validate('GOOGL', docs, tmp_path)
    assert len(paragraphs) == 9
    assert len(summaries) == 3
    assert verdict['status'] == 'PARSER_VALIDATED'
    assert verdict['excluded_pagination_fragments'] == 3
    assert {p['report_date'] for p in paragraphs} == {d['report_date'] for d in docs}
    assert {s['original_passage_count'] for s in summaries} == {4}
    assert {s['passage_count'] for s in summaries} == {3}
    assert all(s['excluded_pagination_fragment_ids'][0].endswith('_Item8_00002') for s in summaries)
    assert not any(p['text'] == '44.' for p in paragraphs)
    assert all(any(p['item'] == item and p['report_date'] == d['report_date']
                   for p in paragraphs) for d in docs for item in ('1A','7','8'))
    assert len(verdict['pagination_exclusion_audit']) == 3


def test_real_numeric_table_cells_remain_and_fail_text_check(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    fake_parser(monkeypatch, lambda d: valid_output(d, is_table=True))
    with pytest.raises(c.CoverageError, match='invalid or replacement-character'):
        c.parse_and_validate('GOOGL', docs, tmp_path)


def test_short_prose_remains_invalid(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    fake_parser(monkeypatch, lambda d: valid_output(d, marker='short'))
    with pytest.raises(c.CoverageError, match='invalid or replacement-character'):
        c.parse_and_validate('GOOGL', docs, tmp_path)


def test_replacement_char_remains_invalid(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    fake_parser(monkeypatch, lambda d: valid_output(d, marker='REVENUE\ufffdVALUE'))
    with pytest.raises(c.CoverageError, match='invalid or replacement-character'):
        c.parse_and_validate('GOOGL', docs, tmp_path)


def test_page_number_in_risk_factors_is_not_filtered(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    fake_parser(monkeypatch, lambda d: valid_output(d, marker='44.', section='1A'))
    with pytest.raises(c.CoverageError, match='invalid or replacement-character'):
        c.parse_and_validate('GOOGL', docs, tmp_path)


def test_parser_summary_count_mismatch_fails_closed(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    def corrupt(d):
        rows, summary = valid_output(d)
        summary[0]['passage_count'] += 1
        return rows, summary
    fake_parser(monkeypatch, corrupt)
    with pytest.raises(c.CoverageError, match='raw parser summary/count mismatch'):
        c.parse_and_validate('GOOGL', docs, tmp_path)


def test_page_fragment_does_not_relabel_source_passage_ids(monkeypatch, tmp_path):
    docs = [record(y) for y in (2025, 2024, 2023)]
    fake_parser(monkeypatch, lambda d: valid_output(d, marker='87.'))
    passages, summaries, result = c.parse_and_validate('GOOGL', docs, tmp_path)
    assert all(p['passage_id'].endswith('_00001') for p in passages)
    assert Counter(p['item'] for p in passages) == Counter({'1A':3, '7':3,'8':3})
    assert result['pagination_exclusion_audit'][0]['page_labels'] == ['87.']

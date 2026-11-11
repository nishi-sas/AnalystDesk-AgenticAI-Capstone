"""Offline SEC sidecar staging regression tests; no network calls."""
from __future__ import annotations

from pathlib import Path
import pytest

from tools import build_verified_coverage as m


def rec(ticker='MSFT'):
    return {'ticker': ticker, 'report_date': '2026-06-30',
            'accession': '000119312526323660',
            'local_path': 'data/edgar_cache/documents/CIK0000789019/000119312526323660/msft-20260630.htm'}


def put(root, record, *, with_meta=True):
    path = root / record['local_path']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'FORM 10-K SAMPLE ' * 200)
    if with_meta:
        Path(str(path) + '.meta.json').write_text('{"test": "provenance"}\n', encoding='utf-8')
    return path


def test_original_cached_html_and_metadata_both_staged(tmp_path):
    source, stage, record = tmp_path / 'source', tmp_path / 'stage', rec()
    html = put(source, record)
    m.stage_document(record, source, stage)
    assert (stage / record['local_path']).read_bytes() == html.read_bytes()
    assert Path(str(stage / record['local_path']) + '.meta.json').read_bytes() == Path(str(html) + '.meta.json').read_bytes()


def test_restage_cannot_overwrite_sidecar_conflict(tmp_path):
    source, stage, record = tmp_path / 'source', tmp_path / 'stage', rec()
    put(source, record)
    m.stage_document(record, source, stage)
    Path(str(stage / record['local_path']) + '.meta.json').write_text('tampered')
    with pytest.raises(m.CoverageError, match='conflict'):
        m.stage_document(record, source, stage)


def test_missing_source_sidecar_is_not_invented(tmp_path):
    source, stage, record = tmp_path / 'source', tmp_path / 'stage', rec()
    put(source, record, with_meta=False)
    m.stage_document(record, source, stage)
    assert (stage / record['local_path']).is_file()
    assert not Path(str(stage / record['local_path']) + '.meta.json').exists()


def test_newly_accepted_candidate_publishes_html_and_metadata(tmp_path):
    source, repo, record = tmp_path / 'stage', tmp_path / 'repo', rec('ADBE')
    html = put(source, record)
    m._publish_new_docs([record], source, repo)
    assert (repo / record['local_path']).read_bytes() == html.read_bytes()
    assert Path(str(repo / record['local_path']) + '.meta.json').read_bytes() == Path(str(html) + '.meta.json').read_bytes()


def test_publish_rejects_missing_new_candidate_metadata(tmp_path):
    source, repo, record = tmp_path / 'stage', tmp_path / 'repo', rec('ADBE')
    put(source, record, with_meta=False)
    with pytest.raises(m.CoverageError, match='provenance'):
        m._publish_new_docs([record], source, repo)


def test_publish_rejects_existing_conflicting_provenance(tmp_path):
    source, repo, record = tmp_path / 'stage', tmp_path / 'repo', rec('ADBE')
    put(source, record)
    put(repo, record)
    Path(str(repo / record['local_path']) + '.meta.json').write_text('untrusted')
    with pytest.raises(m.CoverageError, match='overwrite'):
        m._publish_new_docs([record], source, repo)


def test_staging_rejects_provenance_symlink(tmp_path):
    source, stage, record = tmp_path / 'source', tmp_path / 'stage', rec()
    p = put(source, record)
    sidecar = Path(str(p) + '.meta.json')
    sidecar.unlink()
    try:
        sidecar.symlink_to(p)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation unavailable on this OS')
    with pytest.raises(m.CoverageError, match='Unsafe'):
        m.stage_document(record, source, stage)

"""Offline tests for previously verified SEC cache reuse (no network)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from tools import build_verified_coverage as s


def example(ticker: str, year: int) -> dict:
    acc = f'{year:018d}'
    return {'ticker': ticker, 'report_date': f'{year}-11-30',
            'accession': acc, 'local_path':
            f'data/edgar_cache/documents/CIK0000796343/{acc}/adbe-{year}.htm'}


def prepare(repo: Path, ticker: str='ADBE', *, published: bool=True):
    docs = [example(ticker, y) for y in (2025, 2024, 2023)]
    for d in docs:
        path = repo / d['local_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'VALID SEC DOCUMENT' * 100)
        Path(str(path) + '.meta.json').write_text('{"downloaded_at": "earlier"}')
    if published:
        release = repo / 'data/verified_coverage/runs/old_release'
        release.mkdir(parents=True)
        (release / '10k_verified_manifest.json').write_text(json.dumps(docs))
        (repo / 'data/verified_coverage/current.json').write_text(json.dumps({
            'schema': 'analystdesk-verified-coverage-pointer-v1',
            'manifest': 'data/verified_coverage/runs/old_release/10k_verified_manifest.json'}))
    return docs


def test_prior_manifest_stages_all_three_metadata_pairs(tmp_path):
    repo, stage = tmp_path / 'repo', tmp_path / 'stage'
    docs = prepare(repo)
    assert s.stage_prior_verified_replacement('ADBE', stage, repo) == 3
    for d in docs:
        source = repo / d['local_path']
        target = stage / d['local_path']
        assert source.read_bytes() == target.read_bytes()
        assert Path(str(source) + '.meta.json').read_bytes() == Path(str(target) + '.meta.json').read_bytes()


def test_previous_filing_cache_is_reused_not_clobbered_by_downloader(monkeypatch, tmp_path):
    repo, stage = tmp_path / 'repo', tmp_path / 'stage'
    docs = prepare(repo)
    def fake_run(command, **kwargs):
        for d in docs:
            base = stage / d['local_path']
            assert base.is_file()
            assert json.loads(Path(str(base)+'.meta.json').read_text())['downloaded_at'] == 'earlier'
        manifest = stage / 'evidence/10k_html_manifest.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(docs))
        return subprocess.CompletedProcess(command, 0, 'CACHED', '')
    monkeypatch.setattr(s.subprocess, 'run', fake_run)
    result = s.download_replacement('ADBE', stage, repo)
    assert len(result) == 3
    s._publish_new_docs(result, stage, repo)
    for d in docs:
        meta = Path(str(repo / d['local_path'])+'.meta.json')
        assert json.loads(meta.read_text())['downloaded_at'] == 'earlier'


def test_no_prior_release_does_not_invent_cache(tmp_path):
    assert s.stage_prior_verified_replacement('ADBE',tmp_path/'stage',tmp_path/'repo')==0


def test_prior_release_different_company_not_staged(tmp_path):
    repo, stage=tmp_path/'repo',tmp_path/'stage'
    prepare(repo)
    assert s.stage_prior_verified_replacement('CRM',stage,repo)==0


def test_previously_published_manifest_requires_three_years(tmp_path):
    repo, stage=tmp_path/'repo',tmp_path/'stage'
    docs=prepare(repo)
    manifest=repo/'data/verified_coverage/runs/old_release/10k_verified_manifest.json'
    manifest.write_text(json.dumps(docs[:2]))
    with pytest.raises(s.CoverageError,match='three'):
        s.stage_prior_verified_replacement('ADBE',stage,repo)
    assert not stage.exists()


def test_previous_provenance_missing_fails_closed(tmp_path):
    repo, stage=tmp_path/'repo',tmp_path/'stage'
    docs=prepare(repo)
    Path(str(repo/docs[0]['local_path'])+'.meta.json').unlink()
    with pytest.raises(s.CoverageError,match='sidecar'):
        s.stage_prior_verified_replacement('ADBE',stage,repo)
    assert not stage.exists()


def test_traversal_pointer_fails_closed(tmp_path):
    repo,stage=tmp_path/'repo',tmp_path/'stage'
    prepare(repo)
    pointer=repo/'data/verified_coverage/current.json'
    pointer.write_text(json.dumps({'schema':'analystdesk-verified-coverage-pointer-v1',
                                    'manifest':'../outside.json'}))
    with pytest.raises(s.CoverageError,match='Unsafe'):
        s.stage_prior_verified_replacement('ADBE',stage,repo)


def test_no_existing_provenance_can_be_overwritten(tmp_path):
    repo,stage=tmp_path/'repo',tmp_path/'stage'
    docs=prepare(repo)
    assert s.stage_prior_verified_replacement('ADBE',stage,repo)==3
    meta=Path(str(stage/docs[0]['local_path'])+'.meta.json')
    meta.write_text('{"downloaded_at":"tampered"}')
    with pytest.raises(s.CoverageError,match='conflict'):
        s.stage_prior_verified_replacement('ADBE',stage,repo)


def test_hash_mismatch_does_not_stage(tmp_path):
    repo,stage=tmp_path/'repo',tmp_path/'stage'
    docs=prepare(repo)
    docs[0]['sha256']='0'*64
    (repo/'data/verified_coverage/runs/old_release/10k_verified_manifest.json').write_text(json.dumps(docs))
    with pytest.raises(s.CoverageError, match='SHA256'):
        s.stage_prior_verified_replacement('ADBE',stage,repo)

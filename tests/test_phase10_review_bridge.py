"""Review UI contract: stage identity, hashes, approval safety, Docker isolation."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re

import pytest

from phase10_bridge import BridgeError
import phase10_review_bridge as review

TID = 'f' * 32
NAME = 'ui_stage4c3_' + TID + '_abcd1234'


def make_review(root: Path, *, phase='STAGE4C_READY_FOR_HUMAN_REVIEW',
                verdicts=('SUPPORTED', 'SUPPORTED'), change_review=None) -> Path:
    evidence = root / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    markdown = '# Verified comparison\n\nNot human-approved.\n'
    sha = hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    r = {
        'source_thread_id': TID, 'draft_sha256': sha, 'critic_review_performed': True,
        'model_semantic_assessment_performed': True, 'human_report_approved': False,
        'report_submitted_for_review': False, 'publication_performed': False,
        'semantic_entailment_checked': False,
        'hard_blockers': [], 'claim_count': len(verdicts),
        'findings': [{'claim_id':f'claim_{i}', 'verdict':v} for i,v in enumerate(verdicts)],
    }
    if change_review:
        r.update(change_review)
    manifest = {
        'status': 'PASS', 'thread_id': TID, 'phase': phase, 'revision_count': 0,
        'human_report_approved': False, 'report_submitted_for_review': False,
        'publication_performed': False,
        'versions': [{
            'version': 0, 'draft_sha256': sha,
            'draft_path': f'evidence/{NAME}_v0_draft.md',
            'review_path': f'evidence/{NAME}_v0_review.json',
        }],
    }
    (evidence / f'{NAME}_v0_draft.md').write_text(markdown, encoding='utf-8')
    (evidence / f'{NAME}_v0_review.json').write_text(json.dumps(r), encoding='utf-8')
    path = evidence / f'{NAME}_manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return path


def test_reviewed_no_human_approval(tmp_path):
    make_review(tmp_path)
    r = review.validate_review_bundle(tmp_path, TID, NAME)
    assert r['ready_for_human_review'] is True
    assert r['supported'] == r['claim_count'] == 2
    assert r['human_report_approved'] is False
    assert r['publication_performed'] is False
    assert 'Verified comparison' in r['draft_markdown']


def test_unsupported_claim_must_not_be_ready(tmp_path):
    make_review(tmp_path, phase='STAGE4C_REVIEW_BLOCKED',
                verdicts=('SUPPORTED', 'UNSUPPORTED'))
    r = review.validate_review_bundle(tmp_path, TID, NAME)
    assert r['ready_for_human_review'] is False


def test_review_without_model_assessment_not_ready(tmp_path):
    make_review(tmp_path, change_review={'model_semantic_assessment_performed': False})
    assert review.validate_review_bundle(tmp_path, TID, NAME)['ready_for_human_review'] is False


def test_tampered_draft_rejected(tmp_path):
    make_review(tmp_path)
    (tmp_path / 'evidence' / f'{NAME}_v0_draft.md').write_text('changed', encoding='utf-8')
    with pytest.raises(BridgeError):
        review.validate_review_bundle(tmp_path, TID, NAME)


def test_fake_approval_rejected(tmp_path):
    make_review(tmp_path, change_review={'human_report_approved': True})
    with pytest.raises(BridgeError):
        review.validate_review_bundle(tmp_path, TID, NAME)


def test_file_traversal_rejected(tmp_path):
    path = make_review(tmp_path)
    obj = json.loads(path.read_text())
    obj['versions'][0]['draft_path'] = '../../secret'
    path.write_text(json.dumps(obj))
    with pytest.raises(BridgeError):
        review.validate_review_bundle(tmp_path, TID, NAME)


def test_wrong_thread_rejected(tmp_path):
    make_review(tmp_path)
    with pytest.raises(BridgeError):
        review.validate_review_bundle(tmp_path, '1'*32, NAME)


def test_duplicate_prefix_rejected(tmp_path):
    make_review(tmp_path)
    with pytest.raises(BridgeError):
        review.validate_review_bundle(tmp_path, TID, '../evil')


def test_isolated_review_docker_contract(tmp_path, monkeypatch):
    # No external process or model call: inspect the exact argv offered to Docker.
    (tmp_path / '.env').write_text('OPENROUTER_API_KEY=SECRET_NOT_IN_COMMAND\n')
    monkeypatch.setattr(review, 'ROOT', tmp_path)
    commands = []
    async def fake_docker(argv, *, timeout):
        commands.append(argv)
        if argv[:2] == ['docker', 'ps']:
            return b'123456789abc\n'
        if argv[:2] == ['docker', 'inspect']:
            return ('sha256:' + 'a'*64 + '\n').encode()
        if argv[:2] == ['docker', 'exec']:
            return b'20261101T100701Z_1219a55c\n'
        if argv[:2] == ['docker', 'run']:
            assert '--volumes-from' in argv and '123456789abc' in argv
            assert 'analyst_desk.stage4c3_cli' in argv
            assert '--offline' not in argv
            assert not any('SECRET_NOT_IN_COMMAND' in x for x in argv)
            assert 'ANALYSTDESK_VERIFIED_RELEASE_ID=20261101T100701Z_1219a55c' in argv
            assert 'stage4c4_cli' not in argv
            # Create the expected evidence files to simulate a completed job.
            prefix = argv[argv.index('--prefix') + 1].split('/')[-1]
            original = review._PREFIX_RE
            assert original.fullmatch(prefix)
            global NAME
            old = NAME
            NAME = prefix
            try:
                make_review(tmp_path)
            finally:
                NAME = old
            return json.dumps({'status':'PASS', 'thread_id':TID}).encode()
        raise AssertionError(argv)
    monkeypatch.setattr(review, '_run_docker', fake_docker)
    monkeypatch.setattr(review, '_run_review_cli', fake_docker)
    out = asyncio.run(review.run_live_review(TID))
    assert out['ready_for_human_review'] is True
    assert len([c for c in commands if c[:2] == ['docker','run']]) == 1

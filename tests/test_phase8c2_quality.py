"""All tests are offline, scripted; no model, MCP, approval or publication calls."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from analyst_desk.phase7d_evaluation import (_load_fixed_fixture, SyntheticCanonicalMCP,
    ScriptedWriterClient, scripted_critic, scripted_rewriter)
from analyst_desk.stage4c1_writer import OpenRouterReportWriter
from analyst_desk.phase8c_architecture import paired_downstream_evaluation, synthetic_smoke
from analyst_desk.phase8c2_quality import (QualityReviewError, check_receipt, build_queue,
    label_template, score_review, digest, claims_from_report)
from analyst_desk.phase8c2_cli import main

ROOT=Path(__file__).resolve().parents[1]
THREAD='b3a5fcf8dbdb430ba814727b7c0dab14'

def fixture(*, capture=True):
    p,e=_load_fixed_fixture(ROOT)
    def writer(_):
        return OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
            client=ScriptedWriterClient('neutral'),editorial_lessons=[])
    receipt=asyncio.run(paired_downstream_evaluation(p,e,thread_id=THREAD,
        allowed=('MSFT','GOOGL'),budget=80000,call=SyntheticCanonicalMCP(),
        writer_factory=writer,critic_factory=lambda _:scripted_critic,
        rewriter_factory=lambda _:scripted_rewriter,max_revisions=2,
        capture_review_materials=capture))
    receipt['publication_performed']=False   # Real live wrapper adds this flag.
    return receipt

def reviewed(queue):
    labels=label_template(queue)
    refs={x['unit_id']:x['citation_ids'] for x in queue['review_units']}
    for l in labels:
        l.update({'verdict':'SUPPORTED','checked_citations':refs[l['unit_id']],
                  'source_read_in_full':True,'reason':'Reviewed the cited original local filing passage against this claim.',
                  'reviewer_id':'IndependentReviewer_001','human_attested':True})
    return labels

def test_old_receipt_requires_new_capture_for_quality():
    r=fixture(capture=False)
    assert check_receipt(r)['status']=='REPORT_TEXT_NOT_CAPTURED'
    with pytest.raises(QualityReviewError,match='REPORT_TEXT_NOT_CAPTURED'):
        check_receipt(r,require_materials=True)

def test_receipt_from_capture_has_valid_integrity():
    r=fixture()
    assert check_receipt(r)['has_original_reports'] is True
    assert [x['configuration'] for x in r['review_materials']]==['C0','C1','C2']
    assert r['human_approval_performed'] is False

def test_capture_opt_in_does_not_modify_default_mode():
    r=asyncio.run(synthetic_smoke(ROOT))
    assert 'review_materials' not in r
    assert r['real_llm_calls']==0

def test_no_raw_model_text_in_existing_summary():
    r=fixture(capture=False)
    assert 'review_materials' not in r
    assert r['heldout_quality_measured'] is False

def test_tamper_draft_rejected():
    r=fixture()
    r['review_materials'][0]['draft_markdown']+=' published'
    with pytest.raises(QualityReviewError,match='CAPTURED_REPORT_INTEGRITY'):
        check_receipt(r,require_materials=True)

def test_tamper_financial_hash_rejected():
    r=fixture()
    r['financial_section_sha256']='0'*64
    with pytest.raises(QualityReviewError):check_receipt(r)

def test_tamper_blocker_rejected():
    r=fixture()
    r['results'][1]['hard_blockers']=[]
    with pytest.raises(QualityReviewError):check_receipt(r)

def test_claim_parser_reads_four_plus_summary():
    r=fixture()
    lengths=[len(claims_from_report(x['draft_markdown'])) for x in r['review_materials']]
    assert lengths==[4,5,5]

def test_blinded_queue_with_provenance_excludes_critic_verdicts():
    r=fixture()
    q,_=build_queue(ROOT,r)
    assert len(q['review_units'])==14
    assert q['model_critic_verdicts_exposed'] is False
    assert all('verdict' not in x and 'configuration' not in x for x in q['review_units'])
    assert all('source_sha256' in passage for unit in q['review_units'] for passage in unit['evidence'])

def test_human_label_template_not_auto_attested():
    q,_=build_queue(ROOT,fixture())
    assert all(x['human_attested'] is False and not x['verdict'] for x in label_template(q))

def test_unattested_template_refuses_scoring():
    r=fixture();q,_=build_queue(ROOT,r)
    with pytest.raises(QualityReviewError,match='HUMAN_LABEL_UNATTESTED'):
        score_review(r,q,label_template(q))

def test_human_attested_labels_score_but_not_heldout():
    r=fixture();q,_=build_queue(ROOT,r)
    result=score_review(r,q,reviewed(q))
    assert result['status']=='SCORED_HUMAN_ATTESTED_DEVELOPMENT_PILOT'
    assert result['review_unit_count']==14
    assert result['independent_reviewer_role_verified'] is False
    assert not result['publication_performed']

def test_edited_queue_refused_even_with_stale_label_hash():
    r=fixture();q,_=build_queue(ROOT,r); labels=reviewed(q)
    q['review_units'][0]['claim_text']='modified'
    with pytest.raises(QualityReviewError,match='HUMAN_LABEL_UNATTESTED'):
        score_review(r,q,labels)

def test_report_receipt_rebinding_refused():
    r=fixture();q,_=build_queue(ROOT,r);labels=reviewed(q)
    r['limitations'].append('new')
    with pytest.raises(QualityReviewError,match='QUEUE_RECEIPT_BINDING'):
        score_review(r,q,labels)

def test_forged_checked_citation_refused():
    r=fixture();q,_=build_queue(ROOT,r);labels=reviewed(q)
    labels[0]['checked_citations'].append('MSFT_2026-06-30_Item1A_99999')
    with pytest.raises(QualityReviewError,match='HUMAN_LABEL_UNATTESTED'):
        score_review(r,q,labels)

def test_cli_capture_without_explicit_optin_is_blocked(tmp_path):
    (tmp_path/'evidence').mkdir()
    rc=main(['capture','--project-root',str(tmp_path),'--out','evidence/capture.json',
             '--thread-id',THREAD])
    assert rc==2 and not (tmp_path/'evidence'/'capture.json').exists()

def test_cli_inspect_reports_old_receipt_unscorable(tmp_path,capsys):
    (tmp_path/'evidence').mkdir()
    (tmp_path/'evidence'/'old.json').write_text(json.dumps(fixture(capture=False)),encoding='utf-8')
    assert main(['inspect','--project-root',str(tmp_path),'--receipt','evidence/old.json'])==0
    assert 'REPORT_TEXT_NOT_CAPTURED' in capsys.readouterr().out

def test_cli_refuses_outside_evidence(tmp_path):
    (tmp_path/'evidence').mkdir()
    assert main(['template','--project-root',str(tmp_path),'--queue','../secrets.json','--out','evidence/labels.jsonl'])==2

def test_total_corpus_refs_match_upload():
    q,_=build_queue(ROOT,fixture())
    assert q['corpus_sha256']==hashlib.sha256((ROOT/'data/parsed/10k_passages.jsonl').read_bytes()).hexdigest()

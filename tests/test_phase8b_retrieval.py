"""Phase 8B isolated retrieval tests with synthetic corpus, no downloaded models."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import numpy as np
import pytest
from analyst_desk.retrieval import build_index
from analyst_desk.phase8b_retrieval import (RetrievalEvaluationError, run_experiment,
    review_queue, score_labeled, source_cases, safe_evidence_output, exclusive_json)

TERMS=('cybersecurity','privacy','regulation','litigation','competition','intellectual','licensing','risk','disclosures','factors')

class TinyEmbedder:
    model_name='synthetic-test-embedding'
    def encode(self,texts):
        return np.asarray([[1+str(t).lower().count(term) for term in TERMS] for t in texts], dtype=np.float32)

class TinyReranker:
    model_name='synthetic-test-reranker'
    def score(self,query,texts):
        q=set(query.lower().split())
        return [float(len(q & set(t.lower().split()))) for t in texts]

@pytest.fixture
def scenario(tmp_path):
    root=tmp_path/'project';(root/'evaluation').mkdir(parents=True);(root/'evidence').mkdir()
    repo_bank=Path(__file__).resolve().parents[1]/'evaluation'/'candidates_v1.jsonl'
    (root/'evaluation'/'candidates_v1.jsonl').write_bytes(repo_bank.read_bytes())
    cases=source_cases(root,'dev');docs=[];targets={}
    for i,c in enumerate(cases):
        pid=f"{c['companies'][0]}_{c['reported_period']}_Item1A_{i+1:05d}"
        # All questions have one matched passage in the synthetic source.
        text=' '.join(c['prompt'].split('discussing')[-1].split())+' SEC risk factors.'
        docs.append({'passage_id':pid,'ticker':c['companies'][0],'item':c['item'],
                     'report_date':c['reported_period'],'filing_date':'2026-01-01',
                     'accession':'0000-1234','source_url':'https://www.sec.gov/mock',
                     'source_sha256':'0'*64,'is_table':False,'text':text})
        targets[c['case_id']]=pid
    # Same terms in out-of-scope SEC documents should never appear in any result.
    docs.append({'passage_id':'TSLA_bad','ticker':'TSLA','item':'1A','report_date':'2026-06-30',
                 'filing_date':'2026-01-01','accession':'0000-1234',
                 'source_url':'https://www.sec.gov/mock','source_sha256':'0'*64,
                 'is_table':False,'text':'cybersecurity privacy regulation litigation competition risk'})
    corpus=root/'corpus.jsonl';corpus.write_text('\n'.join(json.dumps(d) for d in docs)+'\n',encoding='utf-8')
    index=root/'index';build_index(corpus,index,TinyEmbedder())
    return root,corpus,index,targets

@pytest.fixture
def run(scenario):
    root,corpus,index,targets=scenario
    pred=run_experiment(root,corpus,index,TinyEmbedder(),TinyReranker(),split='dev')
    return root,corpus,pred,targets


def _labels(root,targets):
    return [{'case_id':c['case_id'],'reviewer':'SEC_reviewer_1','relevant_passage_ids':[targets[c['case_id']]],
             'reason':'Independently inspected the synthetic SEC passage text and matching topic.',
             'reviewed_against_corpus':True,'unanswerable':False} for c in source_cases(root,'dev')]


def test_methods_run_without_gold_and_exact_count(run):
    root,corpus,pred,_=run
    assert pred['status']=='PREDICTIONS_ONLY_NO_GOLD' and pred['retrieval_cases']==8
    assert pred['heldout_accuracy_measured'] is False
    assert all(set(row['methods'])=={'bm25','hybrid','reranked'} for row in pred['results'])


def test_scopes_all_methods_to_ticker_item_and_period(run):
    _,_,pred,_=run
    for row in pred['results']:
        for method in pred['methods']:
            for hit in row['methods'][method]['hits']:
                assert hit['ticker']==row['company'] and hit['item']==row['item']
                assert hit['report_date']==row['report_date'] and 'TSLA' not in hit['passage_id']


def test_queue_blinds_methods_and_requires_source_hash(run):
    _,corpus,pred,_=run
    queue=review_queue(pred,corpus)
    assert queue['status']=='NEEDS_HUMAN_LABELS' and queue['case_count']==8
    assert queue['ranker_identity_exposed'] is False
    assert all('methods' not in str(c) and 'score' not in str(c) and 'latency_ms' not in str(c) for c in queue['cases'])


def test_queue_cannot_use_tampered_corpus(run):
    _,corpus,pred,_=run
    corpus.write_text(corpus.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    with pytest.raises(RetrievalEvaluationError, match='SOURCE_CORPUS_CHANGED'):
        review_queue(pred,corpus)


def test_zero_labels_refuses_to_score(run):
    root,corpus,pred,_=run
    r=score_labeled(root,corpus,pred,[])
    assert r['status']=='INCOMPLETE_LABELS_NOT_SCORED' and r['metrics'] is None


def test_full_human_labels_compute_reference_metrics(run):
    root,corpus,pred,targets=run
    metrics=score_labeled(root,corpus,pred,_labels(root,targets))
    assert metrics['status']=='SCORED_WITH_HUMAN_LABELS'
    assert metrics['split']=='dev' and metrics['heldout_quality_measured'] is False
    assert set(metrics['metrics'])=={'bm25','hybrid','reranked'}
    assert all(0<=m['hit_at_k']<=1 and m['mean_query_latency_ms']>=0 for m in metrics['metrics'].values())


def test_reject_forged_out_of_scope_gold(run):
    root,corpus,pred,targets=run
    labels=_labels(root,targets);labels[0]['relevant_passage_ids']=['TSLA_bad']
    with pytest.raises(RetrievalEvaluationError, match='LABEL_NOT_IN_CANONICAL_SCOPE'):
        score_labeled(root,corpus,pred,labels)


def test_reject_duplicate_labels(run):
    root,corpus,pred,targets=run
    labels=_labels(root,targets);labels.append(copy.deepcopy(labels[0]))
    with pytest.raises(RetrievalEvaluationError,match='LABEL_CASE_UNKNOWN_OR_DUPLICATE'):
        score_labeled(root,corpus,pred,labels)


def test_reject_unattested_labels(run):
    root,corpus,pred,targets=run
    labels=_labels(root,targets);labels[0]['reviewed_against_corpus']=False
    with pytest.raises(RetrievalEvaluationError,match='LABEL_NOT_INDEPENDENTLY_ATTESTED'):
        score_labeled(root,corpus,pred,labels)


def test_reject_empty_gold(run):
    root,corpus,pred,targets=run
    labels=_labels(root,targets);labels[0]['relevant_passage_ids']=[]
    with pytest.raises(RetrievalEvaluationError,match='LABEL_RELEVANCE_EMPTY_OR_DUPLICATE'):
        score_labeled(root,corpus,pred,labels)


def test_prevent_evidence_overwrite_or_escape(scenario):
    root,_,_,_=scenario
    for bad in ('../.env','evaluation/labels.jsonl','evidence/../.env','evidence/sub/foo.json','evidence/foo.txt'):
        with pytest.raises(RetrievalEvaluationError,match='OUTPUT_PATH_UNSAFE'):
            safe_evidence_output(root,bad)
    p=safe_evidence_output(root,'evidence/fresh.json');exclusive_json(p,{'test':'ok'})
    with pytest.raises(RetrievalEvaluationError,match='OUTPUT_ALREADY_EXISTS'):
        safe_evidence_output(root,'evidence/fresh.json')


def test_no_reranker_silently_used_as_three_way_ablation(scenario):
    root,corpus,index,_=scenario
    with pytest.raises(RetrievalEvaluationError,match='RERANKER_REQUIRED'):
        run_experiment(root,corpus,index,TinyEmbedder(),None)


def test_heldout_questions_have_no_labels_in_original_bank(scenario):
    root,_,_,_=scenario
    heldout=source_cases(root,'heldout')
    assert len(heldout)==24
    assert all(c['gold'] is None for c in heldout)


def test_runner_rejects_tampered_frozen_bank(scenario):
    root,corpus,index,_=scenario
    bank=root/'evaluation'/'candidates_v1.jsonl'
    bank.write_text(bank.read_text(encoding='utf-8')+'\n')
    with pytest.raises(Exception,match='FROZEN_BANK_DIGEST_MISMATCH'):
        run_experiment(root,corpus,index,TinyEmbedder(),TinyReranker())


def test_unanswerable_label_excluded_from_reference_recall(run):
    root,corpus,pred,targets=run
    labels=_labels(root,targets)
    labels[0]['relevant_passage_ids']=[]
    labels[0]['unanswerable']=True
    report=score_labeled(root,corpus,pred,labels)
    assert report['status']=='SCORED_WITH_HUMAN_LABELS'
    assert report['unanswerable_cases']==1 and report['answerable_cases']==7

def test_unanswerable_cannot_claim_positive_relevance(run):
    root,corpus,pred,targets=run
    labels=_labels(root,targets);labels[0]['unanswerable']=True
    with pytest.raises(RetrievalEvaluationError,match='LABEL_RELEVANCE_EMPTY_OR_DUPLICATE'):
        score_labeled(root,corpus,pred,labels)

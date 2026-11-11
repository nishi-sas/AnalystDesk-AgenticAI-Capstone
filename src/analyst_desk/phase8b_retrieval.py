"""Phase 8B: evidence-first retrieval A/B/C experiment.

Labels are NEVER inferred from model outputs, retrieval similarity, or filenames.
Reference coverage is limited to the independently supplied relevance judgments.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import time
from collections import Counter
from typing import Any

from .phase8a_evaluation import load_bank
from .retrieval import (Index, bm25_scores, hybrid_search, load_index, load_passages,
                        RetrievalError)

METHODS = ('bm25', 'hybrid', 'reranked')
ID_RE = re.compile(r'RET\d{3}\Z')


class RetrievalEvaluationError(ValueError):
    pass


def _bad(code: str):
    raise RetrievalEvaluationError(code)


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_cases(root: Path, split: str):
    if split not in ('dev', 'heldout'):
        _bad('SPLIT_INVALID')
    rows = [c for c in load_bank(root) if c['task'] == 'retrieval' and c['split'] == split]
    expected = 8 if split == 'dev' else 24
    if len(rows) != expected:
        _bad('RETRIEVAL_CASE_COUNT_MISMATCH')
    return rows


def _scope(record: dict, case: dict) -> bool:
    return (record.get('ticker') in case['companies']
            and record.get('item') == case['item']
            and record.get('report_date') == case['reported_period'])


def _to_hit(record: dict) -> dict:
    return {'passage_id':record['passage_id'], 'source_sha256':record['source_sha256'],
            'ticker':record['ticker'], 'item':record['item'],
            'report_date':record['report_date']}


def _bm25(index: Index, query: str, case: dict, k: int) -> list[dict]:
    values = bm25_scores(index, query)
    matches = [i for i, record in enumerate(index.records) if _scope(record, case) and values[i] > 0]
    matches.sort(key=lambda i: (-float(values[i]), index.records[i]['search_id']))
    seen, out = set(), []
    for i in matches:
        record = index.records[i]
        if record['passage_id'] not in seen:
            seen.add(record['passage_id'])
            out.append(_to_hit(record))
            if len(out) == k:
                break
    return out


def run_experiment(root: Path, corpus: Path, index_dir: Path, embedder, reranker,
                   *, split: str = 'dev', top_k: int = 5) -> dict:
    """Runs real BM25, hybrid RRF and cross-encoder reranking against same SEC index.

    No LLM, portal, or publication. Model construction/warmup excluded from measured query latency.
    """
    if not 1 <= top_k <= 10:
        _bad('TOP_K_OUT_OF_RANGE')
    if reranker is None:
        _bad('RERANKER_REQUIRED_FOR_THREE_WAY_COMPARISON')
    root, corpus, index_dir = Path(root), Path(corpus), Path(index_dir)
    cases = source_cases(root, split)
    index = load_index(index_dir, corpus=corpus, expected_model=embedder.model_name)
    if not index.records:
        _bad('INDEX_EMPTY')
    if not all(isinstance(r.get('source_sha256'), str) and len(r['source_sha256']) >= 6 for r in index.records):
        _bad('INDEX_MISSING_SOURCE_PROVENANCE')
    output = []
    for case in cases:
        item, ticker, date = case['item'], case['companies'][0], case['reported_period']
        case_results = {}
        for method in METHODS:
            start = time.perf_counter_ns()
            if method == 'bm25':
                hits = _bm25(index, case['prompt'], case, top_k)
            else:
                hits = hybrid_search(index, case['prompt'], embedder,
                                     ticker=ticker, item=item, report_date=date,
                                     top_n=top_k, candidate_k=max(30,top_k),
                                     reranker=reranker if method == 'reranked' else None)
                hits = [_to_hit(h) for h in hits]
            elapsed_ms = (time.perf_counter_ns()-start)/1e6
            if len({h['passage_id'] for h in hits}) != len(hits) or any(not _scope(h,case) for h in hits):
                _bad('HITS_DUPLICATED_OR_SCOPE_VIOLATION')
            case_results[method] = {'hits':hits, 'latency_ms':round(elapsed_ms,3)}
        output.append({'case_id':case['case_id'], 'split':split, 'company':ticker,
                       'item':item, 'report_date':date, 'methods':case_results})
    return {'phase':'PHASE8B_RETRIEVAL_ABLATION', 'status':'PREDICTIONS_ONLY_NO_GOLD',
            'experiment_type':'REAL_LOCAL_RETRIEVAL_MODELS', 'split':split, 'top_k':top_k,
            'retrieval_cases':len(cases), 'corpus_sha256':digest(corpus),
            'index_embedding_model':index.manifest['embedding_model'],
            'reranker_model':getattr(reranker,'model_name','unspecified'),
            'source_inventory_sha256':digest(root/'evaluation'/'candidates_v1.jsonl'),
            'methods':list(METHODS), 'results':output,
            'heldout_accuracy_measured':False,
            'limitations':['No relevance labels are inferred from retriever outputs',
                           'Index/model warmup excluded; timings measure per-query execution only',
                           'Labels must be independently adjudicated before retrieval accuracy is reported',
                           'A relevance pool may omit relevant passages; reported recall is against labeled references only']}


def review_queue(predictions: dict, corpus: Path, *, pool_limit: int = 15) -> dict:
    if predictions.get('phase') != 'PHASE8B_RETRIEVAL_ABLATION' or predictions.get('status') != 'PREDICTIONS_ONLY_NO_GOLD':
        _bad('PREDICTIONS_INVALID')
    if digest(corpus) != predictions.get('corpus_sha256'):
        _bad('SOURCE_CORPUS_CHANGED')
    if not 1 <= pool_limit <= 30:
        _bad('POOL_LIMIT_INVALID')
    documents = {p['passage_id']:p for p in load_passages(corpus)}
    queue = []
    for row in predictions['results']:
        if set(row.get('methods',{})) != set(METHODS):
            _bad('METHOD_SET_MISMATCH')
        candidate_ids = set()
        for method in METHODS:
            candidate_ids.update(h['passage_id'] for h in row['methods'][method]['hits'])
        # Deterministic, query-specific shuffling, independent from algorithm rankings.
        randomized = sorted(candidate_ids)
        random.Random('phase8b-blind-v1:'+row['case_id']).shuffle(randomized)
        passages=[]
        for pid in randomized[:pool_limit]:
            if pid not in documents:
                _bad('PREDICTED_PASSAGE_NOT_IN_CORPUS')
            doc = documents[pid]
            if any(doc[k]!=row[rk] for k,rk in [('ticker','company'),('item','item'),('report_date','report_date')]):
                _bad('PREDICTED_PASSAGE_SCOPE_INVALID')
            passages.append({'passage_id':pid, 'source_sha256':doc['source_sha256'],
                             'item':doc['item'], 'text_excerpt':doc['text'][:620]})
        queue.append({'case_id':row['case_id'], 'company':row['company'], 'item':row['item'],
                      'report_date':row['report_date'], 'blinded_candidates':passages,
                      'reviewer_instruction':'Judge relevance from SEC source. Do not infer relevance from inclusion or order in this pool. Independently search corpus if needed.'})
    return {'phase':'PHASE8B_BLIND_RELEVANCE_QUEUE', 'status':'NEEDS_HUMAN_LABELS',
            'split':predictions['split'], 'corpus_sha256':predictions['corpus_sha256'],
            'case_count':len(queue),'ranker_identity_exposed':False,'cases':queue}


def score_labeled(root: Path, corpus: Path, predictions: dict, labels: list[dict]) -> dict:
    """Scores only fully labeled cases. Labels must be created outside this runner."""
    if predictions.get('phase') != 'PHASE8B_RETRIEVAL_ABLATION':
        _bad('PREDICTION_RECEIPT_INVALID')
    if digest(corpus) != predictions.get('corpus_sha256'):
        _bad('SOURCE_CORPUS_CHANGED')
    split = predictions.get('split')
    cases = {c['case_id']:c for c in source_cases(root, split)}
    if {r['case_id'] for r in predictions.get('results',[])} != set(cases):
        _bad('PREDICTION_CASES_NOT_COMPLETE')
    docs = {p['passage_id']:p for p in load_passages(corpus)}
    if not isinstance(labels,list):_bad('LABELS_INVALID')
    by_id={}
    unanswerable=set()
    for label in labels:
        if not isinstance(label,dict) or set(label) != {'case_id','reviewer','relevant_passage_ids','reason','reviewed_against_corpus','unanswerable'}:
            _bad('LABEL_SCHEMA_INVALID')
        cid=label['case_id']
        if cid not in cases or cid in by_id:
            _bad('LABEL_CASE_UNKNOWN_OR_DUPLICATE')
        if (not isinstance(label['reviewer'],str) or not 3<=len(label['reviewer'])<=80
                or not isinstance(label['reason'],str) or len(label['reason'])<15
                or label['reviewed_against_corpus'] is not True):
            _bad('LABEL_NOT_INDEPENDENTLY_ATTESTED')
        gold=label['relevant_passage_ids']
        if (not isinstance(label['unanswerable'],bool) or not isinstance(gold,list)
                or len(gold)>30 or any(not isinstance(pid,str) for pid in gold)
                or len(gold)!=len(set(gold)) or bool(gold)==label['unanswerable']):
            _bad('LABEL_RELEVANCE_EMPTY_OR_DUPLICATE')
        for pid in gold:
            if not isinstance(pid,str) or pid not in docs or not _scope(docs[pid],cases[cid]):
                _bad('LABEL_NOT_IN_CANONICAL_SCOPE')
        by_id[cid] = set(gold)
        if label['unanswerable']: unanswerable.add(cid)
    # Held-out results require ALL independently annotated cases; same for development metrics.
    if set(by_id)!=set(cases):
        return {'phase':'PHASE8B_RETRIEVAL_SCORING', 'status':'INCOMPLETE_LABELS_NOT_SCORED',
                'split':split, 'labeled':len(by_id), 'needed':len(cases), 'metrics':None,
                'heldout_quality_measured':False}
    metrics = {}
    answerable=set(cases)-unanswerable
    for method in METHODS:
        scores, hits, reciprocal, latency = [], [], [], []
        for row in predictions['results']:
            if row['case_id'] in unanswerable: continue
            ranked=[h['passage_id'] for h in row['methods'][method]['hits']]
            if len(ranked)!=len(set(ranked)) or len(ranked)>predictions['top_k']:
                _bad('PREDICTION_RANKING_INVALID')
            gold=by_id[row['case_id']]
            positions=[i+1 for i,pid in enumerate(ranked) if pid in gold]
            scores.append(len(set(ranked)&gold)/len(gold))
            hits.append(int(bool(positions)))
            reciprocal.append(1/min(positions) if positions else 0.)
            value=row['methods'][method]['latency_ms']
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                _bad('LATENCY_INVALID')
            latency.append(value)
        metrics[method] = {'labeled_reference_recall_at_k':round(sum(scores)/len(scores),4) if scores else None,
                           'hit_at_k':round(sum(hits)/len(hits),4) if hits else None,
                           'mrr_at_k':round(sum(reciprocal)/len(reciprocal),4) if reciprocal else None,
                           'mean_query_latency_ms':round(sum(latency)/len(latency),3) if latency else None}
    return {'phase':'PHASE8B_RETRIEVAL_SCORING', 'status':'SCORED_WITH_HUMAN_LABELS',
            'split':split, 'case_count':len(cases), 'answerable_cases':len(answerable),
            'unanswerable_cases':len(unanswerable), 'top_k':predictions['top_k'],
            'metrics':metrics, 'heldout_quality_measured':split=='heldout',
            'reference_coverage':'HUMAN_LABELED_PASSAGES_NOT_ASSUMED_EXHAUSTIVE',
            'limitations':['Reviewer attestations are not cryptographic or independent verification of annotator identity',
                           'Labeled-reference recall is not corpus-exhaustive retrieval recall',
                           'Scoring requires review of actual SEC passage text, not rankings alone']}


def safe_evidence_output(root: Path, out: str) -> Path:
    root=Path(root).resolve(); evidence=root/'evidence'
    path=Path(out)
    if (path.is_absolute() or len(path.parts)!=2 or path.parts[0]!='evidence'
            or path.suffix not in ('.json','.jsonl') or not re.fullmatch(r'[A-Za-z0-9_.-]+',path.name)
            or path.name.startswith('.') or '..' in path.name or evidence.is_symlink()
            or (evidence.exists() and not evidence.is_dir())):
        _bad('OUTPUT_PATH_UNSAFE')
    evidence.mkdir(exist_ok=True)
    target = evidence/path.name
    if target.exists() or target.is_symlink():
        _bad('OUTPUT_ALREADY_EXISTS_OR_UNSAFE')
    return target


def exclusive_json(path: Path, obj: dict):
    # Prevent overwrite of evidence. JSON is never executed.
    with path.open('x',encoding='utf-8') as fh:
        json.dump(obj,fh,sort_keys=True,ensure_ascii=False,indent=2)
        fh.write('\n')

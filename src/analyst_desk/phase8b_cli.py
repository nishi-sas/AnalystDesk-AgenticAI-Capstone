"""Phase 8B retrieval evaluation runner; no agent, MCP or publication actions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .phase8b_retrieval import (RetrievalEvaluationError, run_experiment, review_queue,
                                 score_labeled, safe_evidence_output, exclusive_json)
from .retrieval import (SentenceEmbedder, CrossEncoderReranker, DEFAULT_EMBEDDING_MODEL,
                        DEFAULT_RERANKER_MODEL)


def main(argv=None):
    p=argparse.ArgumentParser(description='AnalystDesk Phase 8B retrieval evaluation')
    p.add_argument('action',choices=['run','queue','score'])
    p.add_argument('--out',required=True)
    p.add_argument('--corpus',default='data/parsed/10k_passages.jsonl')
    p.add_argument('--index',default='data/retrieval_index')
    p.add_argument('--split',choices=['dev','heldout'],default='dev')
    p.add_argument('--top-k',type=int,default=5)
    p.add_argument('--model',default=DEFAULT_EMBEDDING_MODEL)
    p.add_argument('--reranker',default=DEFAULT_RERANKER_MODEL)
    p.add_argument('--predictions')
    p.add_argument('--labels')
    args=p.parse_args(argv)
    root=Path.cwd()
    try:
        path=safe_evidence_output(root,args.out)
        if args.action=='run':
            if args.predictions or args.labels:raise RetrievalEvaluationError('UNEXPECTED_ARGUMENT')
            embedder=SentenceEmbedder(args.model)
            reranker=CrossEncoderReranker(args.reranker)
            result=run_experiment(root,Path(args.corpus),Path(args.index),embedder,reranker,
                                  split=args.split,top_k=args.top_k)
        else:
            if not args.predictions:raise RetrievalEvaluationError('PREDICTIONS_REQUIRED')
            pred_path=Path(args.predictions)
            if (pred_path.is_symlink() or not pred_path.is_file() or not pred_path.resolve().is_relative_to((root/'evidence').resolve())):
                raise RetrievalEvaluationError('PREDICTIONS_PATH_UNSAFE')
            predictions=json.loads(pred_path.read_text(encoding='utf-8'))
            if args.action=='queue':
                if args.labels:raise RetrievalEvaluationError('LABELS_UNEXPECTED')
                result=review_queue(predictions,Path(args.corpus))
            else:
                if not args.labels:raise RetrievalEvaluationError('LABELS_REQUIRED')
                label_path=Path(args.labels)
                if (label_path.is_symlink() or not label_path.is_file() or not label_path.resolve().is_relative_to((root/'evaluation').resolve())):
                    raise RetrievalEvaluationError('LABELS_PATH_UNSAFE')
                labels=[json.loads(s) for s in label_path.read_text(encoding='utf-8').splitlines() if s.strip()]
                result=score_labeled(root,Path(args.corpus),predictions,labels)
        exclusive_json(path,result)
        summary={k:result[k] for k in ('phase','status','split') if k in result}
        summary['result_path']=str(path)
        if 'retrieval_cases' in result:summary['retrieval_cases']=result['retrieval_cases']
        if 'case_count' in result:summary['case_count']=result['case_count']
        if 'metrics' in result:summary['metrics']=result['metrics']
        print(json.dumps(summary,indent=2))
        return 0
    except (RetrievalEvaluationError,ValueError,OSError,KeyError,TypeError,ImportError) as exc:
        print('PHASE8B_ERROR:'+type(exc).__name__+':'+str(exc)[:140],file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())

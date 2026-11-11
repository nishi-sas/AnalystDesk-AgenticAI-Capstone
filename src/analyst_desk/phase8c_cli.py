"""CLI for Stage 4C paired architecture pilot, evidence-only, fail-closed."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys

from .phase8b_retrieval import safe_evidence_output, exclusive_json, RetrievalEvaluationError
from .phase8c_architecture import (ArchitectureEvalError, synthetic_smoke,
                                     real_approved_pilot, preflight_live)
from .stage4a_config import PROJECT_ROOT


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description='Phase 8C: C0 deterministic, C1 Writer, C2 Writer/Critic/revision pilot')
    p.add_argument('action',choices=['smoke','preflight','live'])
    p.add_argument('--out',required=True)
    p.add_argument('--thread-id',default=None)
    p.add_argument('--allow-model-calls',action='store_true')
    p.add_argument('--upstream-mode',choices=('synthesized','audited'),default='synthesized',
                   help='Shared B3 packet: LLM synthesis (default) or SEC supervisor audit only')
    p.add_argument('--max-client-calls',type=int,default=20)
    p.add_argument('--max-revisions',type=int,choices=[0,1,2],default=2)
    p.add_argument('--project-root',type=Path,default=PROJECT_ROOT)
    args=p.parse_args(argv)
    try:
        root=args.project_root.resolve()
        path=safe_evidence_output(root,args.out)
        if args.action=='smoke':
            if args.thread_id is not None or args.allow_model_calls or args.max_client_calls!=20 or args.max_revisions!=2 or args.upstream_mode!='synthesized':
                raise ArchitectureEvalError('SMOKE_MODE_INVALID_ARGUMENTS')
            result=asyncio.run(synthetic_smoke(root))
        elif args.action=='preflight':
            if not args.thread_id or args.allow_model_calls or args.max_client_calls!=20 or args.max_revisions!=2:
                raise ArchitectureEvalError('PREFLIGHT_MODE_INVALID_ARGUMENTS')
            result=preflight_live(root,args.thread_id,upstream_mode=args.upstream_mode)
        else:
            if not args.allow_model_calls or not args.thread_id:
                raise ArchitectureEvalError('LIVE_MODE_REQUIRES_EXPLICIT_APPROVAL_AND_THREAD_ID')
            if type(args.max_client_calls) is not int or not 1<=args.max_client_calls<=40:
                raise ArchitectureEvalError('INVALID_MODEL_CALL_LIMIT')
            result=asyncio.run(real_approved_pilot(root,args.thread_id,
                max_client_calls=args.max_client_calls,max_revisions=args.max_revisions,
                upstream_mode=args.upstream_mode))
        exclusive_json(path,result)
        print(json.dumps({'phase':result['phase'],'status':result['status'],
                          'experiment_kind':result.get('experiment_kind'),
                          'shared_upstream_mode':result.get('shared_upstream_mode'),
                          'result_path':str(path),'configurations':result.get('configurations',[]),
                          'results':[{'configuration':a['configuration'],
                                      'wall_latency_ms':a['wall_latency_ms'],
                                      'revisions':a['revisions'],
                                      'critic_verdicts':a['critic_verdicts'],
                                      'hard_blockers':a['hard_blockers']} for a in result.get('results',[])],
                          'downstream_usage':result.get('downstream_usage'),
                          'publication_performed':False},indent=2,ensure_ascii=False))
        return 0
    except (ArchitectureEvalError,RetrievalEvaluationError,ValueError,OSError) as exc:
        # No exception repr; credentials/LLM text not printed.
        print('PHASE8C_ERROR:'+type(exc).__name__+':'+str(exc)[:140],file=sys.stderr)
        return 2
    except Exception as exc:
        print('PHASE8C_ERROR:'+type(exc).__name__+':LIVE_RUN_FAILED_SANITIZED',file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())

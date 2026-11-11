"""Phase 8C2 offline independent-review workflow; paid capture requires explicit opt-in."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
from .phase8c2_quality import (QualityReviewError, read_json, check_receipt,
    build_queue, label_template, score_review)
from .phase8c_architecture import ArchitectureEvalError, real_approved_pilot
from .phase8b_retrieval import safe_evidence_output, exclusive_json, RetrievalEvaluationError
from .stage4a_config import PROJECT_ROOT


def safe_input(root:Path, value:str)->Path:
    rel=Path(value)
    evidence=root/'evidence'
    if (rel.is_absolute() or len(rel.parts)!=2 or rel.parts[0]!='evidence' or
        rel.suffix not in ('.json','.jsonl') or
        not re.fullmatch(r'[A-Za-z0-9_.-]+',rel.name) or
        rel.name.startswith('.') or '..' in rel.name or evidence.is_symlink()):
        raise QualityReviewError('REVIEW_INPUT_PATH_UNSAFE')
    path=evidence/rel.name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise QualityReviewError('REVIEW_INPUT_PATH_UNSAFE')
    return path


def main(argv=None):
    p=argparse.ArgumentParser(description='8C2 human review: inspect, capture, queue, template, score')
    p.add_argument('action',choices=('inspect','capture','queue','template','score'))
    p.add_argument('--project-root',type=Path,default=PROJECT_ROOT)
    p.add_argument('--receipt')
    p.add_argument('--queue')
    p.add_argument('--labels')
    p.add_argument('--out')
    p.add_argument('--thread-id')
    p.add_argument('--upstream-mode',choices=('synthesized','audited'),default='audited')
    p.add_argument('--allow-model-calls',action='store_true')
    p.add_argument('--max-client-calls',type=int,default=20)
    p.add_argument('--max-revisions',type=int,choices=(0,1,2),default=2)
    args=p.parse_args(argv)
    try:
        root=args.project_root.resolve()
        if args.action=='inspect':
            if args.out or not args.receipt or args.allow_model_calls or args.thread_id or args.queue or args.labels:
                raise QualityReviewError('INSPECT_ARGS_INVALID')
            receipt=read_json(safe_input(root,args.receipt))
            summary=check_receipt(receipt)
            print(json.dumps({'phase':'PHASE8C2_REVIEW_READINESS',**summary},indent=2))
            return 0
        if not args.out:
            raise QualityReviewError('OUTPUT_REQUIRED')
        out=safe_evidence_output(root,args.out)
        # Refuse spending money or doing work when the destination already exists.
        if out.exists() or out.is_symlink():
            raise QualityReviewError('OUTPUT_ALREADY_EXISTS')
        if args.action=='capture':
            if (not args.allow_model_calls or not args.thread_id or args.receipt or args.queue or args.labels
                or type(args.max_client_calls) is not int or not 1<=args.max_client_calls<=40):
                raise QualityReviewError('CAPTURE_REQUIRES_EXPLICIT_MODEL_OPTIN')
            receipt=asyncio.run(real_approved_pilot(root,args.thread_id,
                max_client_calls=args.max_client_calls,max_revisions=args.max_revisions,
                upstream_mode=args.upstream_mode,capture_review_materials=True))
            check_receipt(receipt,require_materials=True)
            exclusive_json(out,receipt)
            summary={'status':'CAPTURED_UNAPPROVED_REPORTS_FOR_HUMAN_REVIEW',
                     'configuration_count':3,'models_used':True,
                     'downstream_usage':receipt.get('downstream_usage'),
                     'quality_scored':False, 'publication_performed':False}
        else:
            if args.allow_model_calls or args.thread_id or args.max_client_calls!=20 or args.max_revisions!=2:
                raise QualityReviewError('OFFLINE_MODE_REJECTS_LIVE_FLAGS')
            if args.action=='queue':
                if not args.receipt or args.queue or args.labels:raise QualityReviewError('QUEUE_ARGS_INVALID')
                receipt=read_json(safe_input(root,args.receipt))
                queue,_=build_queue(root,receipt)
                exclusive_json(out,queue)
                summary={'status':'BLINDED_QUEUE_REQUIRES_HUMAN_REVIEW','review_units':len(queue['review_units']),
                         'quality_scored':False,'model_calls_performed':0}
            elif args.action=='template':
                if args.receipt or not args.queue or args.labels:raise QualityReviewError('TEMPLATE_ARGS_INVALID')
                queue=read_json(safe_input(root,args.queue))
                if queue.get('status')!='HUMAN_LABELS_REQUIRED' or not isinstance(queue.get('review_units'),list):
                    raise QualityReviewError('QUEUE_INVALID')
                rows=label_template(queue)
                # Use exclusive create, never replace a partially reviewed label file.
                with out.open('x',encoding='utf-8',newline='\n') as f:
                    for x in rows:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n')
                summary={'status':'BLANK_HUMAN_REVIEW_TEMPLATE','review_units':len(rows),
                         'quality_scored':False,'model_calls_performed':0}
            elif args.action=='score':
                if not args.receipt or not args.queue or not args.labels:raise QualityReviewError('SCORE_ARGS_INVALID')
                receipt=read_json(safe_input(root,args.receipt))
                queue=read_json(safe_input(root,args.queue))
                label_path=safe_input(root,args.labels)
                if label_path.stat().st_size>1000000:raise QualityReviewError('LABELS_TOO_LARGE')
                try: labels=[json.loads(x) for x in label_path.read_text(encoding='utf-8').splitlines() if x.strip()]
                except (ValueError,UnicodeError):raise QualityReviewError('LABELS_INVALID_JSONL')
                score=score_review(receipt,queue,labels)
                exclusive_json(out,score)
                summary={'status':score['status'],'review_units':score['review_unit_count'],
                         'arms':score['arms'],'model_calls_performed':0}
            else:raise QualityReviewError('UNKNOWN_ACTION')
        print(json.dumps({'phase':'PHASE8C2_INDEPENDENT_REVIEW','result_path':str(out),**summary},indent=2))
        return 0
    except (QualityReviewError, ArchitectureEvalError,
            RetrievalEvaluationError, ValueError, OSError) as exc:

        code = str(exc)

        # Accept only known, authored stage identifiers.
        safe_stages = {
            'B3_SHARED_UPSTREAM',
            'DOWNSTREAM_MCP_SETUP',
            'C0_DRAFT', 'C0_CRITIC', 'C0_INTEGRITY',
            'C1_DRAFT', 'C1_CRITIC', 'C1_INTEGRITY',
            'C2_WRITER_CRITIC_REVISION', 'C2_INTEGRITY',
        }

        match = re.fullmatch(
            r'STAGE=([A-Z0-9_]{1,40});CODE=([A-Z0-9_]{1,64})',
            code
        )

        if match and match.group(1) in safe_stages:
            code = f'STAGE_{match.group(1)}_CODE_{match.group(2)}'
        elif not re.fullmatch(r'[A-Z0-9_]{1,90}', code):
            code = 'VALIDATION_FAILED_SANITIZED'

        print('PHASE8C2_ERROR:' + code, file=sys.stderr)
        return 2
    except Exception:
        print('PHASE8C2_ERROR:OPERATION_FAILED_SANITIZED',file=sys.stderr)
        return 2
if __name__=='__main__':
    raise SystemExit(main())

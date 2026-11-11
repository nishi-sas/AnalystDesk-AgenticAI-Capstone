"""CLI for conservative Phase 8A evaluation inventory and dev scoring."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from .phase8a_evaluation import EvaluationError, inventory_receipt, input_only_rows, score_predictions

SAFE_OUT=re.compile(r'evidence/[A-Za-z0-9_-]{6,90}\.(?:json|jsonl)\Z')
SAFE_IN=re.compile(r'evidence/[A-Za-z0-9_-]{6,90}\.jsonl\Z')


def _safe_path(root: Path, relative: str, *, suffix: str, writable: bool) -> Path:
    relative=relative.replace('\\','/')
    if not (SAFE_OUT if writable else SAFE_IN).fullmatch(relative) or not relative.endswith(suffix):
        raise EvaluationError('EVIDENCE_PATH_INVALID')
    directory=root/'evidence'
    if directory.is_symlink() or not directory.is_dir() or not directory.resolve().is_relative_to(root):
        raise EvaluationError('EVIDENCE_DIRECTORY_UNSAFE')
    p=root/relative
    if p.is_symlink() or not p.resolve().is_relative_to(directory.resolve()):
        raise EvaluationError('EVIDENCE_DESTINATION_UNSAFE')
    if writable and p.exists():
        raise EvaluationError('EVIDENCE_ALREADY_EXISTS')
    if not writable and (not p.is_file() or p.stat().st_size>200_000):
        raise EvaluationError('PREDICTIONS_MISSING_OR_EXCESSIVE')
    return p


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description='Phase 8A frozen candidate inventory; no model or MCP calls')
    parser.add_argument('action',choices=('lint','export-inputs','score-dev'))
    parser.add_argument('--root',default='.')
    parser.add_argument('--split',choices=('all','dev','heldout'),default='all')
    parser.add_argument('--predictions')
    parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    try:
        root=Path(args.root).resolve()
        output=_safe_path(root,args.out,suffix='.jsonl' if args.action=='export-inputs' else '.json',writable=True)
        if args.action=='lint':
            result=inventory_receipt(root)
        elif args.action=='export-inputs':
            result=input_only_rows(root,args.split)
        else:
            if not args.predictions:
                raise EvaluationError('PREDICTIONS_REQUIRED')
            path=_safe_path(root,args.predictions,suffix='.jsonl',writable=False)
            try:
                predictions=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
            except (ValueError,UnicodeError) as exc:
                raise EvaluationError('PREDICTIONS_INVALID_JSONL') from exc
            result=score_predictions(root,predictions)
        # x = exclusive create; no overwriting previously recorded evidence.
        with output.open('x',encoding='utf-8',newline='\n') as f:
            if args.action=='export-inputs':
                for row in result: f.write(json.dumps(row,sort_keys=True,ensure_ascii=True)+'\n')
            else:
                f.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print(json.dumps({'phase':'PHASE8A_EVALUATION','status':result.get('status','EXPORTED_INPUTS_ONLY') if isinstance(result,dict) else 'EXPORTED_INPUTS_ONLY',
                          'result_path':args.out,'exported_cases':len(result) if isinstance(result,list) else None,
                          'details':result if isinstance(result,dict) else None},indent=2))
        return 0
    except (EvaluationError,OSError,ValueError) as exc:
        print(json.dumps({'phase':'PHASE8A_EVALUATION','status':'BLOCKED',
                          'reason_code':str(exc) if isinstance(exc,EvaluationError) else 'EVALUATION_IO_ERROR',
                          'agent_executed':False,'portal_writes':False}))
        return 2

if __name__=='__main__':
    raise SystemExit(main())

"""Read-only Phase 6D final acceptance evidence aggregation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .phase6d4_acceptance import validate,AcceptanceError

def main(argv=None):
    parser=argparse.ArgumentParser(description='Phase 6D-4 final security evidence collation')
    parser.add_argument('action',choices=['acceptance'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--regression',default='evidence/105_phase6d3_full_regression.txt')
    parser.add_argument('--out',default='evidence/106_phase6d4_acceptance.json')
    args=parser.parse_args(argv)
    root=Path(args.root).resolve()
    target=(root/args.out).resolve()
    if not target.is_relative_to((root/'evidence').resolve()) or target.suffix!='.json':
        print(json.dumps({'status':'BLOCKED','reason_code':'OUTSIDE_EVIDENCE'})); return 2
    try:
        receipt=validate(root,regression_file=args.regression)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps({**receipt,'result_path':str(target.relative_to(root))},indent=2))
        return 0
    except (OSError,ValueError,AcceptanceError) as exc:
        print(json.dumps({'status':'BLOCKED','reason_code':str(exc) if isinstance(exc,AcceptanceError) else type(exc).__name__,
                          'real_portal_writes_performed_by_this_audit':False},indent=2))
        return 2

if __name__=='__main__': raise SystemExit(main())

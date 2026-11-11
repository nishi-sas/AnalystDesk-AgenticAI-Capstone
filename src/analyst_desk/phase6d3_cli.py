"""CLI entrypoint: Phase 6D-3 and candidate-archive secret scan."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .phase6d3_security import SecurityAuditError, audit, scan_submission_zip


def _out_path(root: Path, value: str) -> Path:
    p=(root/value).resolve()
    base=(root/'evidence').resolve()
    if not p.is_relative_to(base) or p.suffix.lower() != '.json':
        raise SecurityAuditError('OUTPUT_MUST_BE_EVIDENCE_JSON')
    base.mkdir(parents=True,exist_ok=True)
    return p


def main(argv=None):
    p=argparse.ArgumentParser(description='Nonpublishing AnalystDesk Phase 6D-3 control audit')
    p.add_argument('action',choices=['audit','zip-scan'])
    p.add_argument('--root',default='.')
    p.add_argument('--zip',default=None)
    p.add_argument('--out',required=True)
    args=p.parse_args(argv)
    try:
        root=Path(args.root).resolve()
        out=_out_path(root,args.out)
        if args.action=='audit': receipt=audit(root)
        else:
            if args.zip is None: raise SecurityAuditError('MISSING_SUBMISSION_ZIP')
            path=Path(args.zip)
            receipt=scan_submission_zip((root/path).resolve() if not path.is_absolute() else path)
        out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps({**receipt,'result_path':str(out.relative_to(root))},indent=2))
        return 0 if receipt['status']=='PASS' else 2
    except (OSError,SecurityAuditError,ValueError) as exc:
        print(json.dumps({'status':'BLOCKED','phase':'PHASE6D3','reason_code':
             str(exc) if isinstance(exc,SecurityAuditError) else type(exc).__name__,
             'actual_portal_publication_performed':False},indent=2))
        return 2

if __name__=='__main__': raise SystemExit(main())

"""Phase 6D-1 reproducible read-only security evidence runner."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .phase6d1_replay import run_replay


def main(argv=None):
    parser=argparse.ArgumentParser(description='AnalystDesk 6D-1 synthetic Writer/Critic attack replay')
    parser.add_argument('command',choices=('run',))
    parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    out=Path(args.out)
    if (out.parent!=Path('evidence') or not out.name.startswith('94_phase6d1_')
            or out.suffix != '.json' or not out.name.isascii() or len(out.name)>96):
        parser.error('--out must be evidence/94_phase6d1_*.json')
    try:
        report=run_replay()
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        summary={k:v for k,v in report.items() if k not in ('results','benign_results')}
        summary['result_path']=out.as_posix()
        print(json.dumps(summary,sort_keys=True,indent=2))
        return 0 if report['status']=='PASS' else 1
    except Exception as exc:
        print(json.dumps({'phase':'PHASE6D1','status':'ERROR','error_type':type(exc).__name__}))
        return 2

if __name__=='__main__':
    raise SystemExit(main())

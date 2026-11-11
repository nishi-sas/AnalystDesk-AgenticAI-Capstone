"""Offline red-team policy audit. Run from project root; never uses network or credentials."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .phase6c_redteam import load_jsonl, run_suite

def main(argv=None):
    p=argparse.ArgumentParser(description='Phase 6C deterministic security boundary evaluation')
    p.add_argument('run',choices=['run'])
    p.add_argument('--attacks',default='security/red_team/attacks.jsonl')
    p.add_argument('--benign',default='security/red_team/benign.jsonl')
    p.add_argument('--out',default='evidence/85_phase6c_redteam_results.json')
    args=p.parse_args(argv)
    out=Path(args.out)
    # prevent arbitrary report writes from attacker-controlled CLI paths
    if out.parent != Path('evidence') or out.suffix!='.json' or not out.name.startswith('85_'):
        p.error('--out must be evidence/85_*.json directly under evidence/')
    try:
        result=run_suite(load_jsonl(args.attacks),load_jsonl(args.benign))
    except Exception as exc:
        # don't print source content or secrets in CLI errors
        print(json.dumps({'status':'ERROR','exception_type':type(exc).__name__}))
        return 2
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    summary={k:result[k] for k in ('phase','status','mode','report_scope','defences_on','defences_off','benign','category_summary')}
    summary['result_path']=out.as_posix()
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':sys.exit(main())

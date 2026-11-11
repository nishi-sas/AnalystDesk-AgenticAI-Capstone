"""Read-only Phase 7B Reflexion lesson preview (no models, MCP or portal)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from .phase7a_reflexion import ReflexionError
from .phase7b_reflexion import retrieve_editorial_lessons


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Preview bounded editorial Reflexion reminders')
    parser.add_argument('command', choices=('preview',))
    parser.add_argument('--analyst-id', required=True)
    parser.add_argument('--companies', default='GOOGL,MSFT')
    parser.add_argument('--root', default='.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    rel = args.out.replace('\\', '/')
    if not re.fullmatch(r'evidence/111_[A-Za-z0-9_-]{3,75}\.json', rel):
        parser.error('--out must be evidence/111_<safe_name>.json')
    root = Path(args.root).resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to((root / 'evidence').resolve()):
        parser.error('output must stay inside evidence directory')
    if target.exists():
        print(json.dumps({'status':'BLOCKED','reason_code':'EVIDENCE_ALREADY_EXISTS'}))
        return 2
    try:
        lessons = retrieve_editorial_lessons(root, analyst_id=args.analyst_id,
                   company_scope=tuple(args.companies.split(',')))
    except (ReflexionError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ReflexionError) else 'STORE_UNAVAILABLE'
        print(json.dumps({'status':'BLOCKED','reason_code':reason}))
        return 2
    receipt = {'phase':'PHASE7B_REFLEXION_PREVIEW', 'status':'PASS',
               'read_only':True, 'lesson_count':len(lessons),
               'lesson_codes':[a['lesson_code'] for a in lessons],
               'model_invocations':0, 'mcp_invocations':0,
               'portal_publication_performed':False,
               'limitations':['Lessons are model-assessed editorial observations, not source evidence',
                              'Zero lessons is normal if no earlier reviewed revision improved']}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n',encoding='utf-8')
    print(json.dumps({**receipt, 'result_path':rel}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

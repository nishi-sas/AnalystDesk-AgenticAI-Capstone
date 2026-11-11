"""Read-only Phase 7C Reflexion safety audit; no model, MCP or portal calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from .phase7a_reflexion import ReflexionError
from .phase7c_safety import guarded_editorial_lessons, store_preflight

_PATTERN = re.compile(r'evidence/114_[A-Za-z0-9_-]{3,75}\.json')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Audit opt-in Reflexion memory safety')
    parser.add_argument('command', choices=['audit'])
    parser.add_argument('--root', default='.')
    parser.add_argument('--analyst-id', required=True)
    parser.add_argument('--companies', default='GOOGL,MSFT')
    parser.add_argument('--ttl-days', type=int, default=90)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    relative = args.out.replace('\\', '/')
    if not _PATTERN.fullmatch(relative):
        parser.error('--out must be evidence/114_<safe_name>.json')
    root = Path(args.root).resolve()
    evidence_root = root / 'evidence'
    if evidence_root.is_symlink() or not evidence_root.resolve().is_relative_to(root):
        parser.error('evidence root cannot be a symlink or escape the project')
    target = (root / relative).resolve()
    if not target.is_relative_to(evidence_root.resolve()):
        parser.error('output must stay inside evidence')
    if target.exists():
        print(json.dumps({'status': 'BLOCKED', 'reason_code': 'EVIDENCE_ALREADY_EXISTS'}))
        return 2
    try:
        scope = tuple(args.companies.split(','))
        health = store_preflight(root)
        lessons = guarded_editorial_lessons(root, analyst_id=args.analyst_id,
                                           company_scope=scope, ttl_days=args.ttl_days)
    except (ReflexionError, OSError) as exc:
        code = str(exc) if isinstance(exc, ReflexionError) else 'LESSON_STORE_UNAVAILABLE_OR_CORRUPT'
        print(json.dumps({'phase': 'PHASE7C_REFLEXION_SAFETY', 'status': 'BLOCKED',
                          'reason_code': code, 'model_invocations': 0,
                          'mcp_invocations': 0, 'publication_performed': False}))
        return 2
    receipt = {
        'phase': 'PHASE7C_REFLEXION_SAFETY', 'status': 'PASS',
        'store_status': health, 'lesson_count': len(lessons),
        'lesson_codes': [lesson['lesson_code'] for lesson in lessons],
        'analyst_scope_isolation': 'EXACT_MATCH_REQUIRED',
        'lesson_ttl_days': args.ttl_days, 'prompt_advice': 'WHITELIST_ONLY',
        'model_invocations': 0, 'mcp_invocations': 0,
        'portal_registration_performed': False,
        'publication_performed': False, 'read_only': True,
        'limitations': [
            'SQLite quick_check detects corruption, not malicious edits producing valid records',
            'Editorial lessons remain model-assessed observations, not SEC evidence',
            'No empirical quality improvement measured until Phase 7D',
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({**receipt, 'result_path': relative}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

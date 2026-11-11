"""Phase 6D-2 read-only SEC financial-integrity acceptance audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from .stage4a_config import PROJECT_ROOT
from .stage4b_cli import approved_plan_from_stage4a
from .stage4c4_portal import load_reviewed_bundle
from .edgar_service import EdgarFactsService
from .phase6d2_financial_integrity import verify_financial_draft


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Phase 6D-2: recompute existing draft against verified, offline SEC XBRL facts')
    parser.add_argument('command', choices=('audit',))
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out', required=True, help='evidence/97_phase6d2_*.json; no other paths accepted')
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    relative = args.out.replace('\\', '/')
    if not re.fullmatch(r'evidence/97_phase6d2_[A-Za-z0-9_.-]{3,70}\.json', relative):
        parser.error('--out must be a simple evidence/97_phase6d2_*.json path')
    root = args.project_root.resolve()
    output = (root / relative).resolve()
    if not output.is_relative_to((root / 'evidence').resolve()):
        parser.error('--out escapes evidence/')
    try:
        plan = approved_plan_from_stage4a(root, args.thread_id)
        bundle = load_reviewed_bundle(root, args.thread_id, args.manifest,
                                      approved_companies=tuple(plan['companies']))
        verdict = verify_financial_draft(bundle, tuple(plan['companies']),
            edgar=EdgarFactsService(root / 'data' / 'edgar_cache', offline=True))
        verdict['draft_sha256'] = bundle['sha256']
        verdict['result_path'] = relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(verdict, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        # No raw report/source content or provider metadata is ever disclosed.
        # ResearchError is restricted to our own stable error codes.
        from .stage4b_research import ResearchError
        reason = str(exc) if isinstance(exc, ResearchError) and str(exc).startswith('PHASE6D2_FINANCIAL_INTEGRITY: ') else 'BOUND_DRAFT_OR_SEC_CACHE_UNAVAILABLE'
        receipt = {'status': 'BLOCKED', 'phase': 'PHASE6D2_FINANCIAL_INTEGRITY',
                   'reason_code': reason.split(': ')[-1],
                   'verification_completed': False,
                   'portal_registration_performed': False, 'publication_performed': False}
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 2


if __name__ == '__main__':
    sys.exit(main())

"""Phase 6B output audit of a previously reviewed draft. Read-only; never signs or publishes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT
from .stage4b_cli import approved_plan_from_stage4a
from .stage4c4_portal import load_reviewed_bundle
from .phase6b_output import run_output_guardrails, OutputGuardrailError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Phase 6B read-only report output security audit')
    parser.add_argument('command', choices=('audit',))
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--model-check', action='store_true', help='Classify ENTIRE output via OpenRouter (strict/fail-closed)')
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve()
        plan = approved_plan_from_stage4a(root, args.thread_id)
        bundle = load_reviewed_bundle(root, args.thread_id, args.manifest,
                                      approved_companies=tuple(plan['companies']))
        if args.model_check:
            from .phase6a_models import load_model_classifiers
            classifier = load_model_classifiers(safety_provider='openrouter').safety
        else:
            classifier = None
        decision = run_output_guardrails(bundle, safety_classifier=classifier,
                                         require_model_checks=args.model_check)
        status = 'PASS' if decision.passed else 'BLOCKED'
        print(json.dumps({
            'status': status, 'phase': 'PHASE6B_OUTPUT_AUDIT',
            'draft_sha256': bundle['sha256'], 'source_count': len(bundle['source_ids']),
            'report_hard_blockers': bundle['blockers'],
            'output_guardrails': decision.receipt(),
            'model_assessment_performed': args.model_check and
                                           'OUTPUT_SAFETY_MODEL' in [c['code'] for c in decision.checks],
            'portal_registration_performed': False,
            'human_report_approved': False, 'publication_performed': False,
        }, indent=2))
        return 0 if decision.passed else 2
    except Exception as exc:
        # Provider exceptions may contain secrets or raw third-party content.
        # Display only a stable error category, never the exception message.
        print(json.dumps({'status': 'ERROR', 'phase': 'PHASE6B_OUTPUT_AUDIT',
                          'error_type': type(exc).__name__, 'publication_performed': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())

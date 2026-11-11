"""Offline Phase 6A input policy smoke CLI, no provider credentials required."""
from __future__ import annotations

import argparse
import json
from .input_guardrails import run_input_guardrails, InputGuardrailError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Phase 6A input guardrails smoke')
    ap.add_argument('check', choices=['check'])
    ap.add_argument('--request', required=True)
    ap.add_argument('--analyst-id', default='demo_analyst')
    ap.add_argument('--require-model-checks', action='store_true')
    args = ap.parse_args(argv)
    try:
        result = run_input_guardrails(args.request, args.analyst_id,
                                      require_model_checks=args.require_model_checks)
        print(json.dumps({'status': 'PASS' if result.passed else 'BLOCKED',
                          'phase': 'PHASE6A_INPUT_POLICY', **result.receipt()}, indent=2))
        return 0 if result.passed else 2
    except InputGuardrailError:
        print(json.dumps({'status': 'ERROR', 'phase': 'PHASE6A_INPUT_POLICY',
                          'message': 'Invalid input guardrails request'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

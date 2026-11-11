"""Opt-in LIVE 6A model classification. No raw user text or credentials in receipts."""
from __future__ import annotations
import argparse
import json
from .input_guardrails import run_input_guardrails
from .phase6a_models import load_model_classifiers


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Phase 6A-2 LIVE classifiers (requires provider keys and HF weights)')
    parser.add_argument('check', choices=['check'])
    parser.add_argument('--request', required=True)
    parser.add_argument('--analyst-id', default='demo_analyst')
    parser.add_argument('--safety-provider', choices=['openrouter','nvidia'], default='openrouter')
    args = parser.parse_args(argv)
    try:
        models = load_model_classifiers(safety_provider=args.safety_provider)
        decision = run_input_guardrails(args.request, args.analyst_id, **models.guardrail_kwargs())
        print(json.dumps({'status': 'PASS' if decision.passed else 'BLOCKED',
                          'phase': 'PHASE6A_MODEL_CHECKS', **decision.receipt()}, indent=2))
        return 0 if decision.passed else 2
    except Exception as exc:
        # Do not serialize provider response bodies, request details, or credentials.
        print(json.dumps({'status': 'ERROR', 'phase': 'PHASE6A_MODEL_CHECKS',
                          'error_type': type(exc).__name__,
                          'message': 'Model configuration or inference unavailable; no model verdict was accepted.'}))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())

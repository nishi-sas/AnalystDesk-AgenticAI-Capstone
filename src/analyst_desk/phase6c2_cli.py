"""Phase 6C-2 opt-in execution: checkpointed graph replay and live classifiers.

Only writes a bounded JSON artifact under evidence/88_* or evidence/89_*.
Does not print inputs, environment secrets or raw provider responses.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from .phase6c_redteam import load_jsonl
from .phase6c2_replay import load_live_adapter, run_live_input_suite, run_graph_replay, run_external_envelope_probe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Phase 6C-2 security replay')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('graph', 'live', 'external'):
        p = sub.add_parser(name)
        p.add_argument('--out', required=True)
        if name == 'live':
            p.add_argument('--profile', choices=('smoke', 'full'), default='smoke')
            p.add_argument('--safety-provider', choices=('openrouter', 'nvidia'), default='openrouter')
    args = parser.parse_args(argv)
    out = Path(args.out)
    prefix = {'graph': '88_', 'live': '89_', 'external': '90_'}[args.command]
    if (out.parent != Path('evidence') or not out.name.startswith(prefix) or
        out.suffix.lower() != '.json' or not out.name.isascii() or len(out.name) > 96):
        parser.error(f'--out must be evidence/{prefix}*.json directly under evidence/')
    try:
        attacks = load_jsonl('security/red_team/attacks.jsonl')
        benign = load_jsonl('security/red_team/benign.jsonl')
        if args.command == 'graph':
            report = run_graph_replay(attacks, benign)
        elif args.command == 'external':
            report = run_external_envelope_probe(attacks)
        else:
            report = run_live_input_suite(attacks, benign,
                    models=load_live_adapter(safety_provider=args.safety_provider),
                    profile=args.profile)
    except Exception as exc:
        # Never print exception messages, attack payloads or provider metadata.
        print(json.dumps({'phase': 'PHASE6C2', 'status': 'ERROR',
                          'error_type': type(exc).__name__}, sort_keys=True))
        return 2
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    # Summary omits attack payloads, and always declares experimental scope.
    summary = {k:v for k,v in report.items() if k != 'results'}
    summary['result_path'] = out.as_posix()
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())

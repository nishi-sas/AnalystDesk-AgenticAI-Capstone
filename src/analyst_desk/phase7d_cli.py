"""Evidence-only CLI for the Phase 7D paired scripted evaluation."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re

from .phase7d_evaluation import ExperimentError, evaluate

_SAFE_OUT = re.compile(r'^evidence/[A-Za-z0-9_-]{6,90}\.json$')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Phase 7D fixed-case scripted Reflexion ON/OFF evaluation')
    parser.add_argument('command', choices=('evaluate',))
    parser.add_argument('--root', default='.')
    parser.add_argument('--engine', choices=('loop', 'graph'), default='loop')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        relative = args.out.replace('\\', '/')
        if not _SAFE_OUT.fullmatch(relative):
            raise ExperimentError('INVALID_OUTPUT_PATH')
        evidence_dir = root/'evidence'
        if evidence_dir.is_symlink() or not evidence_dir.resolve().is_relative_to(root):
            raise ExperimentError('INVALID_EVIDENCE_DIRECTORY')
        if evidence_dir.exists() and not evidence_dir.is_dir():
            raise ExperimentError('INVALID_EVIDENCE_DIRECTORY')
        path = root/relative
        if path.is_symlink() or path.exists():
            raise ExperimentError('EVIDENCE_ALREADY_EXISTS')
        report = asyncio.run(evaluate(root, engine=args.engine))
        evidence_dir.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as file:
            json.dump(report | {'result_path': relative}, file, indent=2, sort_keys=True)
            file.write('\n')
        print(json.dumps(report | {'result_path': relative}, indent=2, sort_keys=True))
        return 0
    except (ExperimentError, OSError, ValueError) as exc:
        # Never output raw model prompts, source documents, or credentials.
        code = str(exc) if isinstance(exc, ExperimentError) else 'PHASE7D_EXECUTION_ERROR'
        print(json.dumps({'phase':'PHASE7D_REFLEXION_PAIRED_EVALUATION','status':'BLOCKED',
                          'reason_code':code}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

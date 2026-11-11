"""Phase 7A opt-in nonpublishing Reflexion importer for Stage4C-3 evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from .phase7a_reflexion import ReflexionError, capture_manifest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Import verified critic revision lessons; no MCP or publication')
    p.add_argument('command', choices=('capture',))
    p.add_argument('--manifest', required=True)
    p.add_argument('--analyst-id', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--root', default='.')
    args = p.parse_args(argv)
    out = args.out.replace('\\', '/')
    if not re.fullmatch(r'evidence/108_[A-Za-z0-9_-]{3,75}\.json', out):
        p.error('--out must be evidence/108_<safe_name>.json')
    root = Path(args.root).resolve()
    target = (root / out).resolve()
    if not target.is_relative_to((root/'evidence').resolve()):
        p.error('output must stay inside evidence directory')
    if target.exists():
        print(json.dumps({'status':'BLOCKED','reason_code':'EVIDENCE_ALREADY_EXISTS'}))
        return 2
    try:
        receipt = capture_manifest(root, args.manifest, analyst_id=args.analyst_id)
    except (ReflexionError, OSError, ValueError, json.JSONDecodeError) as exc:
        # Never emit raw review text, filenames from corrupted JSON or secret-bearing errors.
        print(json.dumps({'status':'BLOCKED', 'reason_code': str(exc) if isinstance(exc, ReflexionError) else 'IMPORT_ERROR'}))
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({**receipt, 'result_path': out}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

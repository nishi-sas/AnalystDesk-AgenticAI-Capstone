"""Idempotent narrow patch for isolated SEC coverage selector (Windows cache-root bug).

Run from the AnalystDesk repository root. The existing parser and corpus remain untouched.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys

TARGET = Path('tools/build_verified_coverage.py')
BACKUP = Path('tools/build_verified_coverage.py.before_isolated_cwd_fix.bak')
OLD = '''            passages, summaries = process_manifest(str(single_manifest),
                                                    cache_root=str(stage_root / "data" / "edgar_cache"),
                                                    max_chars=2400)'''
NEW = '''            # document_parsing resolves manifest local_path relative to cwd.
            # Temporarily use the isolated staging root so its cache-root guard
            # checks staged SEC HTML, not the original repository's paths.
            previous_cwd = Path.cwd()
            try:
                os.chdir(stage_root)
                passages, summaries = process_manifest(
                    str(single_manifest),
                    cache_root=str(stage_root / "data" / "edgar_cache"),
                    max_chars=2400,
                )
            finally:
                os.chdir(previous_cwd)'''

def main() -> int:
    if not TARGET.is_file():
        print(f'ERROR: missing {TARGET}. Extract the original coverage patch first.', file=sys.stderr)
        return 2
    original = TARGET.read_text(encoding='utf-8')
    if NEW in original:
        print('Already applied; no changes needed.')
        return 0
    if original.count(OLD) != 1:
        print('ERROR: unexpected selector source; refusing to patch (no files modified).', file=sys.stderr)
        return 2
    if BACKUP.exists():
        print(f'ERROR: backup already exists at {BACKUP} but patch not present; inspect manually.', file=sys.stderr)
        return 2
    updated = original.replace(OLD, NEW)
    try:
        ast.parse(updated, filename=str(TARGET))
    except SyntaxError as exc:
        print(f'ERROR: invalid patched Python; aborting: {exc}', file=sys.stderr)
        return 2
    shutil.copy2(TARGET, BACKUP)
    TARGET.write_text(updated, encoding='utf-8')
    print(f'Staging-directory working-directory fix applied to {TARGET}')
    print(f'Original backed up to {BACKUP}')
    print('Existing parser, SEC documents, test evidence, corpora, indexes and Docker setup unchanged.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

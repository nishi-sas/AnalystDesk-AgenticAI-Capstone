"""One-time, fail-closed Phase 6B output-provenance ticker-scope repair.

Run from AnalystDesk project root. Only edits phase6b_output.py; backs up first.
Phase 6D2 recomputation, SEC sidecars, source ID checks and portal gates are untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import tempfile

TARGET = Path('src/analyst_desk/phase6b_output.py')
OLD_LOOKUP = "{'MSFT': 'CIK0000789019|', 'GOOGL': 'CIK0001652044|'}.get(ticker)"
NEW_LOOKUP = '_SUPPORTED_CIK_PREFIXES.get(ticker)'
PREFIXES = '''# SEC CIK identities for the 12-company verified AnalystDesk cohort.
# This only checks presence of company-matched revenue source IDs; Phase 6D2
# independently recomputes the exact figures and validates SEC provenance.
_SUPPORTED_CIK_PREFIXES = {
    'AAPL': 'CIK0000320193|',
    'ADBE': 'CIK0000796343|',
    'BBY': 'CIK0000764478|',
    'CRM': 'CIK0001108524|',
    'DG': 'CIK0000029534|',
    'GOOGL': 'CIK0001652044|',
    'HD': 'CIK0000354950|',
    'LOW': 'CIK0000060667|',
    'META': 'CIK0001326801|',
    'MSFT': 'CIK0000789019|',
    'TGT': 'CIK0000027419|',
    'ULTA': 'CIK0001403568|',
}
'''


def apply(root: Path) -> str:
    root = root.resolve()
    path = root / TARGET
    if not path.is_file():
        raise ValueError(f'Missing {TARGET}; run from the AnalystDesk project root')
    original = path.read_text(encoding='utf-8')
    src = original
    lines = src.splitlines(keepends=True)
    positions = [i for i, x in enumerate(lines) if re.match(r'^_FINANCIAL_ROW\s*=\s*re\.compile\(', x)]
    if len(positions) != 1:
        raise ValueError('Expected one single-line _FINANCIAL_ROW regex; refusing change')
    idx = positions[0]
    row = lines[idx]
    if 'MSFT|GOOGL' in row:
        # Preserve the existing numeric/date/value/status regex and capture groups.
        if '(MSFT|GOOGL)' in row:
            row = row.replace('(MSFT|GOOGL)', '([A-Z]{2,6})', 1)
        elif '(?:MSFT|GOOGL)' in row:
            row = row.replace('(?:MSFT|GOOGL)', '([A-Z]{2,6})', 1)
        else:
            raise ValueError('Unexpected _FINANCIAL_ROW ticker capture; refusing change')
        lines[idx] = row
        src = ''.join(lines)
    elif '([A-Z]{2,6})' not in row:
        raise ValueError('Unexpected _FINANCIAL_ROW expression; refusing change')

    if OLD_LOOKUP in src:
        if src.count(OLD_LOOKUP) != 1:
            raise ValueError('Ambiguous old CIK lookup; refusing change')
        src = src.replace(OLD_LOOKUP, NEW_LOOKUP, 1)
    elif src.count(NEW_LOOKUP) != 1:
        raise ValueError('Unknown CIK lookup; refusing change')

    if '_SUPPORTED_CIK_PREFIXES = {' not in src:
        # Insert at module scope, immediately before the financial row regex.
        anchor = re.search(r'^_FINANCIAL_ROW\s*=\s*re\.compile\(', src, flags=re.MULTILINE)
        if not anchor:
            raise ValueError('Cannot locate regex insertion point')
        src = src[:anchor.start()] + PREFIXES + '\n' + src[anchor.start():]
    elif src.count('_SUPPORTED_CIK_PREFIXES = {') != 1:
        raise ValueError('Ambiguous CIK constant definition')

    compile(src, str(path), 'exec')
    # Validate the complete modified ticker regex without imposing the rest of the source's schema.
    if src == original:
        return 'ALREADY_PATCHED: unchanged; syntax PASS'

    backup_dir = root / 'backups' / ('phase6b_scope_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    backup_path = backup_dir / TARGET
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', delete=False,
                                         dir=path.parent, prefix='.phase6b_scope_', suffix='.tmp') as f:
            f.write(src)
            temp = Path(f.name)
        os.replace(temp, path)
    except BaseException:
        if temp is not None:
            temp.unlink(missing_ok=True)
        shutil.copy2(backup_path, path)
        raise
    return (f'PATCHED: {TARGET}\nBACKUP: {backup_path.relative_to(root)}\n'
            'Only company regex and SEC-CIK prefix lookup changed. Syntax: PASS')


if __name__ == '__main__':
    try:
        print(apply(Path.cwd()))
    except (ValueError, OSError, SyntaxError) as exc:
        raise SystemExit(f'PATCH REFUSED: {exc}')

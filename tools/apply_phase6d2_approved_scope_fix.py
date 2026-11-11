"""One-time guarded Phase 6D2 company-scope compatibility patch.

Run from AnalystDesk repository root with its Python environment activated:
    python tools/apply_phase6d2_approved_scope_fix.py

Changes just Phase 6D2's company identifiers / scope guard. Does not alter
metric arithmetic, operands, SEC sidecars, authorization or portal writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import tempfile

TARGET = Path('src/analyst_desk/phase6d2_financial_integrity.py')
COMPANY_SET = "VERIFIED_COMPANIES = frozenset({'AAPL', 'ADBE', 'BBY', 'CRM', 'DG', 'GOOGL', 'HD', 'LOW', 'META', 'MSFT', 'TGT', 'ULTA'})"
OLD_GUARD = "    if not isinstance(companies, tuple) or not companies or any(c not in {'MSFT', 'GOOGL'} for c in companies):"
NEW_GUARD = "    if (not isinstance(companies, tuple) or not companies\n            or any(not isinstance(c, str) or c not in VERIFIED_COMPANIES for c in companies)\n            or len(set(companies)) != len(companies)):"
OLD_ROW = "(MSFT|GOOGL)"
NEW_ROW = "([A-Z]{2,6})"


def apply(root: Path) -> str:
    path = root / TARGET
    if not path.is_file():
        raise ValueError(f'Missing {TARGET}; run from the AnalystDesk project root')
    original = path.read_text(encoding='utf-8')
    text = original

    if COMPANY_SET not in text:
        anchor = "KNOWN = ('operating_margin', 'revenue_growth_yoy')"
        if text.count(anchor) != 1:
            raise ValueError('Expected phase6d2 known-metrics anchor not found exactly once; no changes made')
        text = text.replace(anchor, anchor + '\n' + COMPANY_SET, 1)

    for constant in ('ROW', 'HEADING'):
        lines = text.splitlines(keepends=True)
        hits = [i for i, line in enumerate(lines) if line.startswith(constant + ' = re.compile(')]
        if len(hits) != 1:
            raise ValueError(f'Expected exactly one {constant} declaration; no changes made')
        i = hits[0]
        old_count = lines[i].count(OLD_ROW)
        new_count = lines[i].count(NEW_ROW)
        if old_count == 1:
            lines[i] = lines[i].replace(OLD_ROW, NEW_ROW, 1)
        elif new_count != 1:
            raise ValueError(f'Unexpected {constant} regex: refusing to change parser')
        text = ''.join(lines)

    if text.count(OLD_GUARD) == 1:
        text = text.replace(OLD_GUARD, NEW_GUARD, 1)
    elif text.count(NEW_GUARD) != 1:
        raise ValueError('Expected exact original/new scope guard; no changes made')

    compile(text, str(path), 'exec')
    if text == original:
        return 'ALREADY_PATCHED: unchanged, syntax valid'

    backup_dir = root / 'backups' / ('phase6d2_approved_scope_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    backup = backup_dir / TARGET
    backup.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, backup)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', delete=False, dir=path.parent,
                                         prefix='.phase6d2_fix_', suffix='.tmp') as f:
            f.write(text)
            temp_path = Path(f.name)
        os.replace(temp_path, path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        shutil.copy2(backup, path)
        raise
    return (f'PATCHED: {TARGET}\nBACKUP: {backup.relative_to(root)}\n'
            'SEC arithmetic and provenance checks: unchanged\nPython syntax: PASS')


if __name__ == '__main__':
    try:
        print(apply(Path.cwd().resolve()))
    except (OSError, ValueError, SyntaxError) as exc:
        raise SystemExit(f'ERROR: {exc}')

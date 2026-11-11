"""Conservative one-file Phase 6B provenance lookup fix.

Replaces exactly the known MSFT/GOOGL CIK lookup in phase6b_output.py.
Does not rewrite _FINANCIAL_ROW or any guardrail or arithmetic logic.
Backs up before change; idempotent. Run from the AnalystDesk root.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import tempfile

TARGET = Path('src/analyst_desk/phase6b_output.py')
OLD_LOOKUP = "{'MSFT': 'CIK0000789019|', 'GOOGL': 'CIK0001652044|'}.get(ticker)"
NEW_LOOKUP = '_SUPPORTED_CIK_PREFIXES.get(ticker)'
PREFIXES = """# Fixed issuer identities for the verified 12-company SEC corpus.
# Only the presence of company-matched revenue operands is checked here.
# Phase 6D2 separately recomputes percentages from SEC-verified XBRL.
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
"""


def apply(root: Path) -> str:
    root = root.resolve()
    path = root / TARGET
    if not path.is_file():
        raise ValueError(f'Missing {TARGET}; run from AnalystDesk root')
    original = path.read_text(encoding='utf-8')
    source = original
    # The previous installer incorrectly assumed one exact regex representation.
    # Do not change regex or financial-row detection in this repair.
    if source.count(OLD_LOOKUP) == 1:
        source = source.replace(OLD_LOOKUP, NEW_LOOKUP, 1)
    elif source.count(NEW_LOOKUP) != 1:
        raise ValueError('Expected unique existing CIK lookup not found; file left unchanged')

    if '_SUPPORTED_CIK_PREFIXES = {' not in source:
        anchor = '\ndef run_output_guardrails('
        if source.count(anchor) != 1:
            raise ValueError('Cannot safely insert issuer map; file left unchanged')
        source = source.replace(anchor, '\n' + PREFIXES + anchor, 1)
    elif source.count('_SUPPORTED_CIK_PREFIXES = {') != 1:
        raise ValueError('Issuer map appears more than once; file left unchanged')

    compile(source, str(path), 'exec')
    if source == original:
        return 'ALREADY_PATCHED: no changes'
    backup_dir = root / 'backups' / ('phase6b_cik_only_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    backup_file = backup_dir / TARGET
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_file)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='', dir=path.parent,
                                         prefix='.phase6b_cik_', suffix='.tmp', delete=False) as f:
            f.write(source)
            tmp = Path(f.name)
        os.replace(tmp, path)
    except BaseException:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        shutil.copy2(backup_file, path)
        raise
    return f'PATCHED: {TARGET}\nBACKUP: {backup_file.relative_to(root)}\nFINANCIAL_ROW and all security checks: unchanged'


if __name__ == '__main__':
    try:
        print(apply(Path.cwd()))
    except (ValueError, OSError, SyntaxError) as e:
        raise SystemExit('PATCH REFUSED: ' + str(e))

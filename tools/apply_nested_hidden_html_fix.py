"""Small, idempotent patch for BeautifulSoup decomposed nested style tags.

Run from the AnalystDesk repository root:
    python tools/apply_nested_hidden_html_fix.py
"""
from __future__ import annotations
from pathlib import Path
import shutil
import sys

TARGET = Path('src/analyst_desk/document_parsing.py')
ANCHOR = (
    '    for tag in list(soup.find_all(style=True)):\n'
    '        style = str(tag.get("style", "")).replace(" ", "").lower()'
)
PATCHED = (
    '    for tag in list(soup.find_all(style=True)):\n'
    '        # Decomposing a hidden ancestor invalidates nested tags in this snapshot.\n'
    '        if tag.attrs is None:\n'
    '            continue\n'
    '        style = str(tag.get("style", "")).replace(" ", "").lower()'
)

def main() -> int:
    if not TARGET.is_file():
        print(f'ERROR: {TARGET} not found. Run from AnalystDesk project root.', file=sys.stderr)
        return 2
    original = TARGET.read_text(encoding='utf-8')
    if PATCHED in original:
        print('Already patched; no changes made.')
        return 0
    count = original.count(ANCHOR)
    if count != 1:
        print(f'ERROR: expected exactly one matching HTML traversal block; found {count}. No changes made.', file=sys.stderr)
        return 2
    backup = TARGET.with_name(TARGET.name + '.before_nested_hidden_html_fix.bak')
    if backup.exists():
        print(f'ERROR: backup already exists: {backup}; no changes made.', file=sys.stderr)
        return 2
    shutil.copy2(TARGET, backup)
    try:
        TARGET.write_text(original.replace(ANCHOR, PATCHED, 1), encoding='utf-8')
    except Exception:
        shutil.copy2(backup, TARGET)
        raise
    print(f'Nested-hidden HTML traversal guard applied to {TARGET}')
    print(f'Original backed up to {backup}')
    print('Existing SEC HTML, parsed corpora, checkpoints and Docker configuration unchanged')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

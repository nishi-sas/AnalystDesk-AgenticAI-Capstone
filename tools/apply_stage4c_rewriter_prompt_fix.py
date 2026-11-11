"""Safely adjust the Stage 4C-3 Rewriter instructions, preserving validation/security gates.

Run from the AnalystDesk repository root:
    python tools/apply_stage4c_rewriter_prompt_fix.py
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

TARGET = Path('src/analyst_desk/stage4c3_revision.py')
REPLACEMENTS = (
    (
        'The new text must be meaningfully different and more conservative. ',
        'Revise the text substantively and conservatively: remove unsupported assertions rather than adding guesses or procedural caveats. ',
    ),
    (
        'Do not approve, submit or publish. Preserve that conclusions need independent human review. ',
        'Do not approve, submit or publish. Report-review status belongs in document metadata, never in a cited claim. ',
    ),
    (
        'For themes: 35-500 characters and citations for both companies where evidence exists. ',
        'For themes: write 35-500 characters and cite both companies where evidence exists. Attribute company-specific assertions explicitly to the company supported by its cited passages; do not imply the other company disclosed the same details. ',
    ),
    (
        'For executive_summary: 90-550 characters, mentions both companies, no digits; cite each company.',
        'For executive_summary: 90-550 characters, mention only the approved companies, no digits; cite each company. Include only risk themes supported by the allowed citations; omit unsupported comparisons, unrequested peers and procedural disclaimers.',
    ),
)


def apply(root: Path) -> str:
    path = root / TARGET
    if not path.is_file():
        raise ValueError('Missing src/analyst_desk/stage4c3_revision.py; run from AnalystDesk project root')
    original = path.read_text(encoding='utf-8')
    updated = original
    for old, new in REPLACEMENTS:
        n = updated.count(old)
        if n == 1:
            updated = updated.replace(old, new, 1)
        elif n == 0 and updated.count(new) == 1:
            continue  # Already applied.
        else:
            raise ValueError(f'Unexpected source anchor count ({n}) near: {old[:70]!r}; no changes made')
    compile(updated, str(path), 'exec')
    if updated == original:
        return 'ALREADY_PATCHED: no changes necessary'
    backup_root = root / 'backups' / ('stage4c_rewriter_prompt_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup = backup_root / TARGET
    backup.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, backup)
    try:
        path.write_text(updated, encoding='utf-8')
    except Exception:
        shutil.copy2(backup, path)
        raise
    return f'PATCHED: {TARGET}\nBACKUP: {backup.relative_to(root)}\nPython syntax: PASS'


if __name__ == '__main__':
    try:
        print(apply(Path.cwd().resolve()))
    except (OSError, ValueError, SyntaxError) as exc:
        raise SystemExit(f'ERROR: {exc}')

"""Narrow patch for Stage 4C Rewriter's one-paragraph summary formatting.

Run from AnalystDesk repository root:
    python tools/apply_stage4c_summary_format_fix.py

Only rewrites src/analyst_desk/stage4c3_revision.py. Backs up source, checks
anchors and parses modified code before writing. No model calls.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import shutil

TARGET = Path('src/analyst_desk/stage4c3_revision.py')
MARKER = 'AD_STAGE4C_SUMMARY_FORMAT_20261102'


def patch(source: str) -> str:
    if MARKER in source:
        return source
    # Match the latest installed diagnostic patch, not an older revision.
    if 'AD_STAGE4C_SUMMARY_DIAGNOSTICS_20261102' not in source:
        raise ValueError('Prior Stage 4C summary diagnostics patch not detected; source unchanged.')

    old = 'class OpenRouterTargetedRewriter:'
    added = '''def _normalize_rewriter_summary_whitespace(text: str) -> str:
    """Remove formatting whitespace only; never delete/transform narrative content.

    Numbers remain prohibited and are rejected instead of silently removed.
    The normal Writer summary contract and independent Critic still apply.
    """
    if any(ch.isdigit() for ch in text):
        raise ResearchError('Rewriter summary contains prohibited numbers')
    return ' '.join(text.split())


class OpenRouterTargetedRewriter:'''
    if source.count(old) != 1:
        raise ValueError('Rewriter class anchor mismatch; source unchanged.')
    source = source.replace(old, added, 1)

    old = '''                if claim_id == 'executive_summary' and ('\\n' in v['text'] or any(ch.isdigit() for ch in v['text'])):
                    raise ResearchError('Rewriter summary contains prohibited formatting or numbers')
                return v'''
    new = '''                if claim_id == 'executive_summary':
                    # A JSON string may contain harmless line breaks; collapse whitespace,
                    # then apply all existing summary, citation and semantic checks.
                    v['text'] = _normalize_rewriter_summary_whitespace(v['text'])
                    if v['text'] == ' '.join(previous_text.split()):
                        raise ResearchError('Rewriter did not revise text')
                return v'''
    if source.count(old) != 1:
        raise ValueError('Rewriter format validation anchor mismatch; source unchanged.')
    source = source.replace(old, new, 1)

    old = "        ('prohibited formatting or numbers', 'REWRITER_SUMMARY_FORMAT_REJECTED'),"
    new = "        ('prohibited numbers', 'REWRITER_SUMMARY_NUMBERS_REJECTED'),\n" + old
    if source.count(old) != 1:
        raise ValueError('Rewriter diagnostic mapping anchor mismatch; source unchanged.')
    source = source.replace(old, new, 1)

    source = source.replace(
        'MAX_REVISIONS = 2  # AD_STAGE4C_SUMMARY_DIAGNOSTICS_20261102',
        'MAX_REVISIONS = 2  # AD_STAGE4C_SUMMARY_DIAGNOSTICS_20261102; ' + MARKER,
        1,
    )
    if MARKER not in source:
        raise ValueError('Patch version marker not installed; source unchanged.')
    ast.parse(source, filename=str(TARGET))
    return source


def apply(root: Path) -> str:
    root = root.resolve()
    target = root / TARGET
    if not target.is_file():
        raise ValueError('Missing src/analyst_desk/stage4c3_revision.py; run at project root.')
    before = target.read_text(encoding='utf-8')
    after = patch(before)
    if before == after:
        return 'ALREADY_APPLIED — no changes'
    backup = root / 'backups' / ('stage4c_summary_format_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')) / TARGET
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    try:
        target.write_text(after, encoding='utf-8')
        ast.parse(target.read_text(encoding='utf-8'), filename=str(TARGET))
    except Exception:
        shutil.copy2(backup, target)
        raise
    return ('PATCHED: ' + str(TARGET) + '\nBACKUP: ' + str(backup) +
            '\nResult: whitespace normalized, digits still rejected, citation/critic approval checks unchanged.')


if __name__ == '__main__':
    try:
        print(apply(Path.cwd()))
    except (ValueError, OSError, SyntaxError) as exc:
        raise SystemExit('INSTALLATION ABORTED: ' + str(exc))

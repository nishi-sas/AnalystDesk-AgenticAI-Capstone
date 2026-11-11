"""AnalystDesk Stage 4C: narrow Writer instructions and safe Rewriter diagnostics.

Run at the repository root:
    python tools/apply_stage4c_summary_diagnostics.py

No model calls; backs up modified files and atomically rolls back on error.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import shutil

WRITER = Path('src/analyst_desk/stage4c1_writer.py')
REVISION = Path('src/analyst_desk/stage4c3_revision.py')
CLI = Path('src/analyst_desk/stage4c3_cli.py')
MARKER = 'AD_STAGE4C_SUMMARY_DIAGNOSTICS_20261102'


def exactly_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise ValueError(f'{label}: expected one source anchor; found {n}. No files changed.')
    return text.replace(old, new, 1)


def patch_writer(text: str) -> str:
    if MARKER in text:
        return text
    old = 'Summarize only risk themes supported by the attached cited comparisons. '
    new = (
        'Summarize only risk themes supported by the attached cited comparisons. '
        'Attribute each company-specific risk explicitly to that company; do not present a risk of one company as common to both. '
        'Do not infer causal relationships (for example AI causing infrastructure or intellectual-property risk) '
        'unless the cited filing explicitly links them. Separate unrelated risks rather than combining them into one claim. '
        'Do not claim an absent or unsupported risk; omit it or qualify that the retrieved evidence is insufficient. '
    )
    text = exactly_once(text, old, new, 'Writer prompt')
    return exactly_once(text, 'class OpenRouterReportWriter:',
                        f'# {MARKER}\nclass OpenRouterReportWriter:', 'Writer marker')


def patch_revision(text: str) -> str:
    if MARKER in text:
        return text
    replacements = [
        (
            'The new text must be meaningfully different and more conservative. ',
            'Revise the text substantively and conservatively: remove unsupported assertions instead of adding guesses, cross-company inferences or procedural disclaimers. '
        ),
        (
            'Do not approve, submit or publish. Preserve that conclusions need independent human review. ',
            'Do not approve, submit or publish. Review status belongs in document metadata, never in an SEC-backed claim. '
        ),
        (
            'For themes: 35-500 characters and citations for both companies where evidence exists. ',
            'For themes: 35-500 characters and citations for both companies where evidence exists. Attribute each risk to the company expressly supported by its citations. '
        ),
        (
            'For executive_summary: 90-550 characters, mentions both companies, no digits; cite each company.',
            'For executive_summary: 90-550 characters, mention both companies, no digits; cite each company. '
            'Use separate company-specific assertions; do not infer an AI/IP/infrastructure causal relationship or shared exposure without explicit cited support. '
            'Omit themes with insufficient evidence; do not insert review-process disclaimers.'
        ),
    ]
    for old, new in replacements:
        # Accept already-applied earlier prompt-fix wording; installer still adds diagnostics.
        if text.count(old) == 1:
            text = text.replace(old, new, 1)
        elif text.count(new) == 1:
            pass
        elif 'Revise the text substantively and conservatively:' in text and old.startswith('The new text'):
            # Previous rewriter prompt patch is already installed.
            pass
        elif 'Report-review status belongs in document metadata' in text and old.startswith('Do not approve'):
            pass
        elif 'For themes: write 35-500 characters' in text and old.startswith('For themes'):
            pass
        elif 'For executive_summary: 90-550 characters, mention only the approved' in text and old.startswith('For executive_summary'):
            pass
        else:
            raise ValueError(f'Rewriter prompt anchor unknown: {old[:50]!r}')
    # In previously-patched variants, add the same substantive clarification at a stable spot.
    if 'Attribute each risk to the company expressly supported by its citations.' not in text:
        text = exactly_once(
            text,
            'Every substantive claim must be directly supported by the cited excerpt text. ',
            'Every substantive claim must be directly supported by the cited excerpt text. '
            'Explicitly distinguish the two companies; do not infer causal links or shared risks from separate passages. ',
            'Rewriter source-grounding clarification',
        )

    block = '''def _safe_rewriter_failure_code(exc: Exception) -> str:
    """Only fixed codes leave the backend; never leak source text/provider output."""
    reason = str(exc)
    cases = (
        ('unauthorized citations', 'REWRITER_CITATION_SCOPE_REJECTED'),
        ('schema invalid', 'REWRITER_JSON_SCHEMA_REJECTED'),
        ('output type invalid', 'REWRITER_JSON_TYPES_REJECTED'),
        ('did not revise text', 'REWRITER_UNCHANGED_TEXT'),
        ('prohibited formatting or numbers', 'REWRITER_SUMMARY_FORMAT_REJECTED'),
        ('oversized response', 'REWRITER_RESPONSE_TOO_LARGE'),
    )
    for phrase, code in cases:
        if phrase in reason:
            return code
    return 'REWRITER_OUTPUT_VALIDATION_FAILED'


'''
    text = exactly_once(text, 'class RewriterOutputRetriesExhausted(ResearchError):', block + 'class RewriterOutputRetriesExhausted(ResearchError):', 'diagnostic helper')
    text = exactly_once(text, '    versions = []\n    actions = []\n    while True:', '    versions = []\n    actions = []\n    revision_failure = None\n    while True:', 'loop diagnostic init')
    old = '''        except RewriterOutputRetriesExhausted:
            # Fail closed: retain the last successfully checked, unapproved draft.
            # Other exceptions (including integrity failures) must still propagate.
            phase = 'STAGE4C_REVIEW_BLOCKED'
            break'''
    new = '''        except RewriterOutputRetriesExhausted as exc:
            # Fail closed, retain the last reviewed version; record fixed safe codes only.
            revision_failure = {'code': _safe_rewriter_failure_code(exc),
                                'target_claim_ids': [t['claim_id'] for t in targets]}
            phase = 'STAGE4C_REVIEW_BLOCKED'
            break'''
    text = exactly_once(text, old, new, 'run_revision_loop catch')
    text = exactly_once(text,
        "            'versions': versions, 'revision_actions': actions,\n",
        "            'versions': versions, 'revision_actions': actions,\n            'revision_failure': revision_failure,\n", 'run_revision_loop result')
    text = exactly_once(text,
        "        next_step: str\n",
        "        next_step: str\n        revision_failure: dict | None\n", 'graph state')
    old = '''        except RewriterOutputRetriesExhausted:
            # Stop without replacing the last reviewed draft or recording a revision.
            return {'next_step':'done','phase':'STAGE4C_REVIEW_BLOCKED'}'''
    new = '''        except RewriterOutputRetriesExhausted as exc:
            # Stop without replacing the last reviewed draft or recording a revision.
            rejected_ids = [f['claim_id'] for f in state['review']['findings']
                            if f['verdict'] in ('UNCERTAIN', 'UNSUPPORTED')]
            return {'next_step':'done','phase':'STAGE4C_REVIEW_BLOCKED',
                    'revision_failure': {'code': _safe_rewriter_failure_code(exc),
                                         'target_claim_ids': rejected_ids}}'''
    text = exactly_once(text, old, new, 'graph catch')
    text = exactly_once(text,
        "            'versions':versions,'revision_actions':actions,\n",
        "            'versions':versions,'revision_actions':actions,\n            'revision_failure':state.get('revision_failure'),\n", 'graph result')
    # Sentinel guarantees full-patch idempotency independent of prompt variants.
    text = exactly_once(text,
        'MAX_REVISIONS = 2',
        f'MAX_REVISIONS = 2  # {MARKER}', 'revision version marker')
    return text


def patch_cli(text: str) -> str:
    if "'revision_failure':result.get('revision_failure')" in text:
        return text
    return exactly_once(text,
        "                     'revision_actions':result['revision_actions'],\n",
        "                     'revision_actions':result['revision_actions'],\n"
        "                     'revision_failure':result.get('revision_failure'),\n", 'CLI manifest result')


def apply(root: Path) -> str:
    root = Path(root).resolve()
    transforms = ((WRITER, patch_writer), (REVISION, patch_revision), (CLI, patch_cli))
    existing = {}
    changed = {}
    for rel, transform in transforms:
        p = root / rel
        if not p.is_file():
            raise ValueError(f'Missing {rel}; run at the AnalystDesk project root.')
        source = p.read_text(encoding='utf-8')
        target = transform(source)
        ast.parse(target, filename=str(rel))
        existing[rel] = source
        if source != target:
            changed[rel] = target
    if not changed:
        return 'ALREADY_APPLIED — no files changed'
    backup_root = root / 'backups' / ('stage4c_summary_diag_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    installed = []
    try:
        for rel in changed:
            dest = backup_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)
        for rel, source in changed.items():
            (root / rel).write_text(source, encoding='utf-8')
            installed.append(rel)
    except Exception:
        for rel in installed:
            (root / rel).write_text(existing[rel], encoding='utf-8')
        raise
    return ('PATCHED: ' + ', '.join(map(str, changed)) + '\nBACKUP: ' + str(backup_root) +
            '\nValidated: Python syntax; no model calls; no approval/publication changes.')


if __name__ == '__main__':
    try:
        print(apply(Path.cwd()))
    except (ValueError, OSError, SyntaxError) as exc:
        raise SystemExit(f'INSTALLATION ABORTED: {exc}')

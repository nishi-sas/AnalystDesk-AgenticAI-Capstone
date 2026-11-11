"""Apply a narrowly scoped Stage 4C prompt fix to an existing AnalystDesk checkout.

Usage (from AnalystDesk project root):
    python tools/apply_stage4c_scope_fix.py

Updates only Stage 4B-3 Supervisor and Stage 4C-1 Writer prompt strings.
Never changes the Critic, Rewriter, revision graph, factual evidence, or approval gates.
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

PATCHES = {
    'src/analyst_desk/stage4c1_writer.py': (
        (
            'Mention both Microsoft and Alphabet and only the risk themes supported by the attached cited comparisons. ',
            'Mention only the approved companies listed in the companies field of the user payload; never introduce unrequested companies or industry peers. Summarize only risk themes supported by the attached cited comparisons. ',
        ),
        (
            'This is an UNREVIEWED draft: do not approve, sign, publish or suggest it has passed compliance.',
            'Do not approve, sign or publish. The application marks the document UNREVIEWED separately; do not insert review-status disclaimers or compliance-process assertions into the cited executive_summary.',
        ),
        (
            'canonical evidence IDs for both companies, no Markdown.',
            'canonical evidence IDs for every approved company, no Markdown.',
        ),
    ),
    'src/analyst_desk/stage4b3_supervisor.py': (
        (
            'If evidence is missing, say retrieval was insufficient; NEVER say a filing lacks a risk. ',
            'If evidence is missing for one company, describe only disclosures supported by retrieved passages; NEVER infer a risk is absent. Put retrieval-coverage limits in workflow warnings, not in cited filing claims. ',
        ),
        (
            'Do NOT approve or publish anything. All conclusions remain provisional until human/compliance review.',
            'Do NOT approve or publish anything. Return only evidence-backed analytical comparisons, without human/compliance review-status sentences; the application represents draft status separately.',
        ),
    ),
}


def main() -> int:
    root = Path.cwd()
    proposals: dict[Path, str] = {}
    messages: list[str] = []
    for rel, changes in PATCHES.items():
        path = root / rel
        if not path.is_file():
            raise SystemExit(f'ERROR: {rel} is missing; run from the AnalystDesk project root.')
        text = path.read_text(encoding='utf-8')
        updated = text
        for old, new in changes:
            count = updated.count(old)
            if count == 1:
                updated = updated.replace(old, new, 1)
            elif count == 0 and new in updated:
                messages.append(f'ALREADY PATCHED: {rel}: {old[:52]}...')
            else:
                raise SystemExit(
                    f'ERROR: Expected exactly one unmodified anchor in {rel}; found {count}. '
                    'No files were changed. Inspect version before applying manually.'
                )
        try:
            compile(updated, str(path), 'exec')
        except SyntaxError as exc:
            raise SystemExit(f'ERROR: {rel} would not compile: {exc}; no files changed.')
        if updated != text:
            proposals[path] = updated

    if not proposals:
        print('PASS: Stage 4C scope prompts are already patched (no changes).')
        return 0

    tag = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = root / 'backups' / f'stage4c_scope_fix_{tag}'
    if backup.exists():
        raise SystemExit('ERROR: backup directory collision; no files changed.')
    for path in proposals:
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for path, updated in proposals.items():
        path.write_text(updated, encoding='utf-8')
        print(f'PATCHED: {path.relative_to(root)}')
    for line in messages:
        print(line)
    print(f'BACKUP: {backup.relative_to(root)}')
    print('PASS: prompts updated, Python syntax compiled. Critic and revision graph unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

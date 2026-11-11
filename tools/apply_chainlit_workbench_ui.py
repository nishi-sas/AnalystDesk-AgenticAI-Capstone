"""Fail-closed installer for the AnalystDesk Chainlit workbench UI.

Run from the project root after extracting the archive into that root.
Only presentation files are modified. No SEC/research/approval code is touched.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

EXPECTED_ORIGINAL_SHA256 = '1fc7c7c7e3402a0feffc44ac7e7399fd2dca7aa186d589d297d3952b6091a449'


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').rstrip() + '\n'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def run() -> int:
    root = Path.cwd().resolve()
    original = root / 'chainlit_app.py'
    package = root / 'ui_patch'
    candidates = [
        (package / 'chainlit_app.py', original),
        (package / 'phase10_ui_helpers.py', root / 'phase10_ui_helpers.py'),
    ]
    if not original.is_file() or any(not source.is_file() for source, _ in candidates):
        print('PATCH REFUSED: Run from project root after extracting the archive (ui_patch/ missing).')
        return 2
    if normalized_sha(original) != EXPECTED_ORIGINAL_SHA256:
        # Avoid replacing intervening changes to the working UI.
        print('PATCH REFUSED: chainlit_app.py differs from the inspected source; original left unchanged.')
        return 2
    if candidates[1][1].exists():
        print('PATCH REFUSED: phase10_ui_helpers.py already exists; original left unchanged.')
        return 2
    # Compile both candidates before copying them into project files.
    for source, _ in candidates:
        compile(source.read_text(encoding='utf-8'), str(source), 'exec')
    backup = root / 'backups' / ('chainlit_workbench_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(original, backup / 'chainlit_app.py')
    for source, dest in candidates:
        shutil.copy2(source, dest)
    print('PATCHED: chainlit_app.py; CREATED: phase10_ui_helpers.py')
    print('BACKUP:', backup.relative_to(root))
    print('Backend, planning, MCP, SEC, Critic, and portal code: unchanged')
    print('Python syntax: PASS')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, SyntaxError, UnicodeError) as exc:
        print('PATCH REFUSED:', type(exc).__name__, str(exc))
        sys.exit(2)

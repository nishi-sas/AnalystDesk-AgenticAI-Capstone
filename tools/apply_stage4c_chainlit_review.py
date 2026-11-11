"""Apply the minimal Stage 4C Chainlit patch with an exact-source guard and backup."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import sys

EXPECTED_CHAINLIT_SHA256 = '82cdf77868819b16815fdea48eedb5b64a09680b7843a066b55a06a6c3153c9d'


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').rstrip() + '\n'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def run(root: Path | None = None) -> int:
    root = (root or Path.cwd()).resolve()
    src = root / 'ui_patch'
    original = root / 'chainlit_app.py'
    target_bridge = root / 'phase10_review_bridge.py'
    new_ui = src / 'chainlit_app.py'
    new_bridge = src / 'phase10_review_bridge.py'
    if not (original.is_file() and new_ui.is_file() and new_bridge.is_file()):
        print('PATCH REFUSED: Need chainlit_app.py and ui_patch/ files in project root.')
        return 2
    if normalized_sha(original) != EXPECTED_CHAINLIT_SHA256:
        print('PATCH REFUSED: chainlit_app.py does not match the tested workbench version. No changes made.')
        return 2
    if target_bridge.exists():
        print('PATCH REFUSED: phase10_review_bridge.py already exists. No changes made.')
        return 2
    for source in (new_ui, new_bridge):
        compile(source.read_text(encoding='utf-8'), str(source), 'exec')
    backup = root / 'backups' / ('chainlit_before_stage4c_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(original, backup / 'chainlit_app.py')
    try:
        shutil.copy2(new_bridge, target_bridge)
        shutil.copy2(new_ui, original)
    except Exception:
        shutil.copy2(backup / 'chainlit_app.py', original)
        target_bridge.unlink(missing_ok=True)
        raise
    print('PATCHED: chainlit_app.py')
    print('CREATED: phase10_review_bridge.py')
    print('BACKUP:', backup.relative_to(root))
    print('Docker image, Compose, API, retrieval, report approval and publishing: UNCHANGED')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, UnicodeError, SyntaxError) as exc:
        print('PATCH REFUSED:', type(exc).__name__, str(exc))
        sys.exit(2)

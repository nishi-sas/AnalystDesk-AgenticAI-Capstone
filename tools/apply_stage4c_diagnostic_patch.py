"""Safely add informative Stage 4C CLI errors to an existing Chainlit installation."""
from __future__ import annotations
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import shutil
import sys

OLD_SHA = 'd644ab4b391b6223d09b11c697c84cac032298a1d80675d91335ad21ed572089'

def sha(path: Path):
    text=path.read_text(encoding='utf-8-sig').replace('\r\n','\n').rstrip()+'\n'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def apply(root: Path | None = None) -> int:
    root=(root or Path.cwd()).resolve()
    dst=root/'phase10_review_bridge.py'
    src=root/'ui_patch'/'phase10_review_bridge.py'
    if not dst.is_file() or not src.is_file():
        print('REFUSED: patch file or existing Phase 10 review bridge not found.')
        return 2
    if sha(dst)!=OLD_SHA:
        print('REFUSED: installed Phase 10 review bridge differs from tested release; nothing overwritten.')
        return 2
    compile(src.read_text(encoding='utf-8'), str(src),'exec')
    backup=root/'backups'/('phase10_review_before_diagnostic_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(dst,backup/dst.name)
    shutil.copy2(src,dst)
    print('PATCHED: phase10_review_bridge.py (safe CLI error diagnostics)')
    print('BACKUP:',backup)
    print('Unchanged: Docker image, compose.yaml, API, chainlit_app.py, SEC data, report approvals')
    return 0
if __name__=='__main__':
    try: sys.exit(apply())
    except (OSError,UnicodeError,SyntaxError) as exc:
        print('PATCH ERROR:',type(exc).__name__)
        sys.exit(2)

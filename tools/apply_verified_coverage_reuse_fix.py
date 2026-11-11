"""Conservative cache reuse fix for prior accepted SEC replacement filings.

Patch only tools/build_verified_coverage.py. It seeds the isolated downloader cache
from the currently published, previously parser-validated release. The existing
SEC downloader still checks recent filings. No provenance guards are relaxed.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys

TARGET = Path('tools/build_verified_coverage.py')
BACKUP = Path('tools/build_verified_coverage.py.before_prior_release_cache_reuse.bak')
ANCHOR = 'def download_replacement(ticker: str, stage_root: Path, repo_root: Path) -> list[dict[str, Any]]:'
INSERT = '''def stage_prior_verified_replacement(ticker: str, stage_root: Path,
                                     repo_root: Path) -> int:
    """Reuse identical SEC HTML + metadata from a previously published release.

    The downloader may generate a different .meta.json for the SAME filing
    on a later invocation (e.g. acquisition timestamp). Preserve the earlier
    validated sidecar instead of allowing a conflict at publication.
    Only the currently published, complete, path-confined manifest is trusted.
    The existing downloader STILL performs its ordinary SEC filing selection.
    """
    base = repo_root / "data" / "verified_coverage"
    pointer = base / "current.json"
    if not pointer.exists() and not pointer.is_symlink():
        return 0
    if (pointer.is_symlink() or not pointer.is_file() or
            not pointer.resolve().is_relative_to(repo_root.resolve())):
        raise CoverageError("Unsafe prior verified-coverage pointer")
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CoverageError(f"Invalid prior verified-coverage pointer: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != "analystdesk-verified-coverage-pointer-v1":
        raise CoverageError("Unrecognized prior verified-coverage pointer")
    name = data.get("manifest")
    if not isinstance(name, str):
        raise CoverageError("Prior verified-coverage manifest missing")
    path = Path(name.replace("\\\\", "/"))
    if (path.is_absolute() or ".." in path.parts or
            path.parts[:3] != ("data", "verified_coverage", "runs") or
            path.name != "10k_verified_manifest.json"):
        raise CoverageError("Unsafe prior verified-coverage manifest path")
    manifest_path = repo_root / path
    if (manifest_path.is_symlink() or not manifest_path.is_file() or
            not manifest_path.resolve().is_relative_to(repo_root.resolve())):
        raise CoverageError("Prior verified-coverage manifest missing or unsafe")
    records = read_manifest(manifest_path)
    candidates = [r for r in records if r.get("ticker") == ticker]
    if not candidates:
        return 0
    docs = grouped_three(candidates, ticker)
    # Preflight complete 3-filing HTML AND provenance before copying anything.
    for record in docs:
        rel = safe_document_path(record, repo_root)
        meta = repo_root / (str(rel) + ".meta.json")
        if (meta.is_symlink() or not meta.is_file() or
                not meta.resolve().is_relative_to(repo_root.resolve())):
            raise CoverageError(f"Prior accepted SEC sidecar missing or unsafe: {rel}")
    for record in docs:
        stage_document(record, repo_root, stage_root)
    return len(docs)


'''
OLD = '''    env = dict(os.environ)
    env["PYTHONPATH"]'''
NEW = '''    cached_periods = stage_prior_verified_replacement(ticker, stage_root, repo_root)
    if cached_periods:
        print(f"  REUSED: {ticker} {cached_periods} previously accepted SEC cache pairs", flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"]'''


def patch_source(source: str) -> str:
    if INSERT in source and NEW in source:
        return source
    if INSERT in source or NEW in source:
        raise ValueError('Partial reuse patch detected; no changes made')
    if source.count(ANCHOR) != 1 or source.count(OLD) != 1:
        raise ValueError('Unexpected selector layout; refusing to modify it')
    if ('for rel in (relative, Path(str(relative) + ".meta.json"))' not in source
            or 'standalone_item8_page_number' not in source
            or 'os.chdir(stage_root)' not in source):
        raise ValueError('Missing previous sidecar, pagination or CWD fix; refusing to patch')
    patched = source.replace(ANCHOR, INSERT + ANCHOR, 1).replace(OLD, NEW, 1)
    ast.parse(patched, filename=str(TARGET))
    return patched


def main() -> int:
    if not TARGET.is_file():
        print(f'ERROR: missing {TARGET}; extract ZIP at project root', file=sys.stderr)
        return 2
    previous = TARGET.read_text(encoding='utf-8')
    try:
        updated = patch_source(previous)
    except (ValueError, SyntaxError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    if updated == previous:
        print('Already applied: prior verified release cache reuse')
        return 0
    if BACKUP.exists():
        print(f'ERROR: backup exists without applied patch: {BACKUP}', file=sys.stderr)
        return 2
    shutil.copy2(TARGET, BACKUP)
    temporary = TARGET.with_suffix('.py.tmp')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(TARGET)
    print(f'Prior verified-release SEC cache reuse applied to {TARGET}')
    print(f'Original backed up to {BACKUP}')
    print('No existing SEC caches, original corpus/index, checkpoints or current release altered.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

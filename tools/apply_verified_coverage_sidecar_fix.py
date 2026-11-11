"""Apply verified-coverage SEC document sidecar staging fix (idempotent).

Only modifies tools/build_verified_coverage.py; fails closed if unrecognized.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys

TARGET = Path('tools/build_verified_coverage.py')
BACKUP = Path('tools/build_verified_coverage.py.before_sidecar_staging_fix.bak')
TEST_TARGET = Path('tests/test_verified_coverage_selector.py')
TEST_BACKUP = Path('tests/test_verified_coverage_selector.py.before_sidecar_fixture_fix.bak')
OLD_FIXTURE = '            path.write_bytes(b"REPLACEMENT SEC DOCUMENT" * 100)'
NEW_FIXTURE = '''            path.write_bytes(b"REPLACEMENT SEC DOCUMENT" * 100)
            Path(str(path) + ".meta.json").write_text('{"test": "SEC metadata stub"}')''' 
OLD_STAGE = '''def stage_document(record: dict[str, Any], source_root: Path, target_root: Path) -> None:
    relative = safe_document_path(record, source_root)
    dest = target_root / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.stat().st_size != (source_root / relative).stat().st_size:
            raise CoverageError(f"Staged document conflict: {relative}")
        return
    shutil.copy2(source_root / relative, dest)
'''
NEW_STAGE = '''def stage_document(record: dict[str, Any], source_root: Path, target_root: Path) -> None:
    """Stage filing HTML AND its downloader provenance sidecar.

    The existing strict parser expects <file>.htm.meta.json alongside HTML.
    A genuinely missing source sidecar remains missing so that parsing rejects
    only the affected company; neither fabricate nor relax provenance checks.
    """
    relative = safe_document_path(record, source_root)
    for rel in (relative, Path(str(relative) + ".meta.json")):
        source = source_root / rel
        if rel != relative and not source.exists() and not source.is_symlink():
            continue  # Parser will fail closed if this filing lacks provenance.
        if (source.is_symlink() or not source.is_file() or
                not source.resolve().is_relative_to(source_root.resolve())):
            raise CoverageError(f"Unsafe SEC document or provenance sidecar: {rel}")
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            if (dest.is_symlink() or not dest.is_file() or
                    dest.read_bytes() != source.read_bytes()):
                raise CoverageError(f"Staged SEC file conflict: {rel}")
            continue
        shutil.copy2(source, dest)
'''
OLD_PUBLISH = '''def _publish_new_docs(staged: list[dict[str, Any]], stage_root: Path, repo_root: Path) -> None:
    for record in staged:
        rel = safe_document_path(record, stage_root)
        original = repo_root / rel
        fresh = stage_root / rel
        if original.exists():
            if original.is_symlink() or original.read_bytes() != fresh.read_bytes():
                raise CoverageError(f"Refusing to overwrite existing SEC cache document: {rel}")
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fresh, original)
'''
NEW_PUBLISH = '''def _publish_new_docs(staged: list[dict[str, Any]], stage_root: Path, repo_root: Path) -> None:
    """Keep approved candidate HTML and provenance sidecars together in cache."""
    for record in staged:
        rel = safe_document_path(record, stage_root)
        for entry in (rel, Path(str(rel) + ".meta.json")):
            fresh = stage_root / entry
            if (fresh.is_symlink() or not fresh.is_file() or
                    not fresh.resolve().is_relative_to(stage_root.resolve())):
                raise CoverageError(f"Accepted filing lacks safe SEC provenance: {entry}")
            original = repo_root / entry
            if original.exists() or original.is_symlink():
                if (original.is_symlink() or not original.is_file() or
                        original.read_bytes() != fresh.read_bytes()):
                    raise CoverageError(f"Refusing to overwrite existing SEC cache file: {entry}")
                continue
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fresh, original)
'''


def patch_source(source: str) -> str:
    if NEW_STAGE in source and NEW_PUBLISH in source:
        return source
    if source.count(OLD_STAGE) != 1 or source.count(OLD_PUBLISH) != 1:
        raise ValueError('Unknown or partially patched selector; no changes made')
    # Require previous cwd fix, since sidecar staging alone won't resolve its path bug.
    if 'os.chdir(stage_root)' not in source or 'os.chdir(previous_cwd)' not in source:
        raise ValueError('Prior isolated-cwd fix not found; no changes made')
    result = source.replace(OLD_STAGE, NEW_STAGE).replace(OLD_PUBLISH, NEW_PUBLISH)
    ast.parse(result, filename=str(TARGET))
    return result


def main() -> int:
    if not TARGET.is_file() or not TEST_TARGET.is_file():
        print('ERROR: missing selector or original regression fixture; extract coverage package first.', file=sys.stderr)
        return 2
    original = TARGET.read_text(encoding='utf-8')
    test_original = TEST_TARGET.read_text(encoding='utf-8')
    try:
        updated = patch_source(original)
        if NEW_FIXTURE in test_original:
            test_updated = test_original
        elif test_original.count(OLD_FIXTURE) == 1:
            test_updated = test_original.replace(OLD_FIXTURE, NEW_FIXTURE)
        else:
            raise ValueError('Unknown original test fixture; no changes made')
        ast.parse(test_updated, filename=str(TEST_TARGET))
    except (ValueError, SyntaxError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    if updated == original and test_updated == test_original:
        print('Already applied: SEC provenance sidecar staging and publication fix.')
        return 0
    for target, backup, old, new in ((TARGET, BACKUP, original, updated),
                                     (TEST_TARGET, TEST_BACKUP, test_original, test_updated)):
        if new != old and backup.exists():
            print(f'ERROR: backup exists but source not patched: {backup}', file=sys.stderr)
            return 2
    for target, backup, old, new in ((TARGET, BACKUP, original, updated),
                                     (TEST_TARGET, TEST_BACKUP, test_original, test_updated)):
        if new != old:
            shutil.copy2(target, backup)
            temp = target.with_suffix(target.suffix + '.tmp')
            temp.write_text(new, encoding='utf-8')
            temp.replace(target)
    print(f'SEC HTML + .meta.json sidecar fix applied to {TARGET}')
    print('Original selector and its offline downloader fixture backed up independently.')
    print('Primary SEC parser, source corpus, index, checkpoints, Docker and Chainlit untouched.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

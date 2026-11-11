"""Idempotent, fail-closed narrow patch for verified-coverage pagination fragments.

Run from AnalystDesk repo root. Changes ONLY tools/build_verified_coverage.py.
No SEC sources, core parser, primary corpus, index or version pointer modified.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys

TARGET = Path('tools/build_verified_coverage.py')
BACKUP = Path('tools/build_verified_coverage.py.before_pagination_filter_fix.bak')

HELPER = '''def standalone_item8_page_number(p: dict[str, Any]) -> bool:
    """Recognize only non-table standalone printed page numbers, e.g. '44.'.

    Does not strip numeric table cells, prose, short risk disclosures, or any
    replacement-character text. Never renumbers/relabels original citations.
    """
    return (p.get("item") == "8" and p.get("is_table") is False
            and isinstance(p.get("text"), str)
            and re.fullmatch(r"[1-9][0-9]{0,2}\\.", p["text"].strip()) is not None)


'''

OLD_LOOP = '''        all_passages.extend(passages)
        all_summaries.extend(summaries)
    result = verify_parser_output(ticker, docs, all_passages, all_summaries)
    return all_passages, all_summaries, result
'''

NEW_LOOP = '''        # SEC iXBRL sometimes produces printed page-number-only text blocks
        # (e.g. Google Item 8 '44.'). These are not financial content.
        # Do NOT alter the core parser or drop any other short/invalid text.
        excluded = [p for p in passages if standalone_item8_page_number(p)]
        kept = [p for p in passages if not standalone_item8_page_number(p)]
        if len(summaries) != 1 or summaries[0].get("passage_count") != len(passages):
            raise CoverageError(f"{ticker} {doc['report_date']}: raw parser summary/count mismatch")
        if excluded:
            summaries[0]["original_passage_count"] = len(passages)
            summaries[0]["passage_count"] = len(kept)
            summaries[0]["excluded_pagination_fragment_ids"] = [
                p["passage_id"] for p in excluded
            ]
            summaries[0]["excluded_pagination_fragment_texts"] = [
                p["text"] for p in excluded
            ]
        all_passages.extend(kept)
        all_summaries.extend(summaries)
    result = verify_parser_output(ticker, docs, all_passages, all_summaries)
    removed = [
        {"report_date": s["report_date"],
         "passage_ids": s.get("excluded_pagination_fragment_ids", []),
         "page_labels": s.get("excluded_pagination_fragment_texts", [])}
        for s in all_summaries if s.get("excluded_pagination_fragment_ids")
    ]
    result["excluded_pagination_fragments"] = sum(len(x["passage_ids"]) for x in removed)
    result["pagination_exclusion_audit"] = removed
    return all_passages, all_summaries, result
'''

ANCHOR = 'def parse_and_validate(ticker: str, docs: list[dict[str, Any]],'


def patch_source(src: str) -> str:
    if HELPER in src and NEW_LOOP in src:
        return src
    if HELPER in src or NEW_LOOP in src:
        raise ValueError('Partial pagination patch found; no changes made')
    if src.count(ANCHOR) != 1 or src.count(OLD_LOOP) != 1:
        raise ValueError('Unknown selector structure; no changes made')
    if 'os.chdir(stage_root)' not in src or 'for rel in (relative, Path(str(relative) + ".meta.json"))' not in src:
        raise ValueError('Previous CWD/sidecar fixes not detected; no changes made')
    result = src.replace(ANCHOR, HELPER + ANCHOR, 1).replace(OLD_LOOP, NEW_LOOP, 1)
    ast.parse(result, filename=str(TARGET))
    return result


def main() -> int:
    if not TARGET.is_file():
        print(f'ERROR: {TARGET} not found; run from AnalystDesk repo root.', file=sys.stderr)
        return 2
    original = TARGET.read_text(encoding='utf-8')
    try:
        updated = patch_source(original)
    except (ValueError, SyntaxError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    if updated == original:
        print('Already applied: isolated pagination-fragment filtering.')
        return 0
    if BACKUP.exists():
        print(f'ERROR: backup already exists without applied patch: {BACKUP}', file=sys.stderr)
        return 2
    shutil.copy2(TARGET, BACKUP)
    temp = TARGET.with_suffix(TARGET.suffix + '.tmp')
    temp.write_text(updated, encoding='utf-8')
    temp.replace(TARGET)
    print(f'Pagination-only filtering applied to {TARGET}')
    print(f'Previous selector backed up as {BACKUP}')
    print('Original SEC filings, parser, two-company corpus/index, checkpoints and Docker unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

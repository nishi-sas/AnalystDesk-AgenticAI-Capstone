"""Read-only diagnostics for GOOGL exclusions in AnalystDesk verified coverage.

Reads the original SEC cache, source manifest and existing parser. Creates a
transient filtered manifest in the OS temporary directory; never edits the
canonical corpus, index, version pointer, SEC HTML, or parser.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
import tempfile

REPLACEMENT = "\ufffd"


def reason(text: object) -> list[str]:
    flags = []
    if not isinstance(text, str):
        return ["not a string"]
    if len(text.strip()) < 10:
        flags.append("under 10 non-whitespace characters")
    if REPLACEMENT in text:
        flags.append(f"contains {text.count(REPLACEMENT)} U+FFFD replacement characters")
    return flags


def contexts(text: str, *, limit: int = 6, span: int = 90) -> list[str]:
    positions = [n for n, ch in enumerate(text) if ch == REPLACEMENT]
    return [repr(text[max(0, pos-span):min(len(text), pos+span+1)]) for pos in positions[:limit]]


def main() -> int:
    repo_root = Path.cwd()
    manifest = repo_root / 'evidence' / '10k_html_manifest.json'
    if not manifest.is_file():
        print('ERROR: run from the AnalystDesk project root with a 36-filing manifest.', file=sys.stderr)
        return 2
    from analyst_desk.document_parsing import process_manifest
    records = json.loads(manifest.read_text(encoding='utf-8'))
    google = [r for r in records if isinstance(r, dict) and r.get('ticker') == 'GOOGL']
    if len(google) != 3 or len({r.get('report_date') for r in google}) != 3:
        print('ERROR: expected exactly three Google reporting periods.', file=sys.stderr)
        return 2

    print('GOOGL source filings:')
    for record in sorted(google, key=lambda r: r['report_date'], reverse=True):
        source_rel = record.get('local_path')
        if not isinstance(source_rel, str):
            print('ERROR: filing record lacks local_path.', file=sys.stderr)
            return 2
        source = (repo_root / source_rel).resolve()
        cache = (repo_root / 'data' / 'edgar_cache').resolve()
        if not source.is_relative_to(cache) or source.is_symlink() or not source.is_file():
            print('ERROR: file missing or path not confined to original SEC cache.', file=sys.stderr)
            return 2
        raw = source.read_bytes()
        print(' ', record['report_date'], '| bytes:', len(raw),
              '| UTF-8 U+FFFD bytes:', raw.count(b'\xef\xbf\xbd'),
              '| UTF-8 strict:', 'yes' if _valid_utf8(raw) else 'no')
    with tempfile.TemporaryDirectory(prefix='analystdesk_google_diagnostic_') as tmp:
        one_company = Path(tmp) / 'google_manifest.json'
        one_company.write_text(json.dumps(google, ensure_ascii=False), encoding='utf-8')
        passages, summaries = process_manifest(str(one_company),
                                              cache_root=str(repo_root / 'data' / 'edgar_cache'),
                                              max_chars=2400)
    print('\nGOOGL parser output:')
    print('  total passages:', len(passages))
    for (date, item), count in sorted(Counter((p.get('report_date'), p.get('item')) for p in passages).items()):
        print(' ', date, 'Item', item, ':', count)
    faulty = [p for p in passages if reason(p.get('text'))]
    print('\nRejected by selector text check:', len(faulty))
    for p in faulty[:20]:
        text = p.get('text')
        print('\n  DATE:', p.get('report_date'), 'ITEM:', p.get('item'), 'PASSAGE:', p.get('passage_id'))
        print('  REASON:', '; '.join(reason(text)), 'LENGTH:', len(text) if isinstance(text, str) else '<not text>')
        if isinstance(text, str):
            if REPLACEMENT in text:
                for fragment in contexts(text):
                    print('  CONTEXT:', fragment)
            else:
                print('  CONTENT:', repr(text[:250]))
    if len(faulty) > 20:
        print('  ...', len(faulty)-20, 'additional invalid passages omitted')
    print('\nDIAGNOSTIC COMPLETE. No SEC files, indexes, corpora or version pointers changed.')
    if faulty:
        print('Do not remove or replace these passages until the source bytes have been inspected.')
    return 0


def _valid_utf8(raw: bytes) -> bool:
    try:
        raw.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


if __name__ == '__main__':
    raise SystemExit(main())

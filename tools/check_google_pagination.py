"""Read-only SEC Google pagination preflight for the verified-coverage patch.

Run from the AnalystDesk project root, after applying the pagination fix.
Does not write any project files or alter SEC corpus/index/version pointers.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
import tempfile

from tools.build_verified_coverage import standalone_item8_page_number


def main() -> int:
    root = Path.cwd().resolve()
    manifest = root / 'evidence' / '10k_html_manifest.json'
    if not manifest.is_file():
        print('ERROR: run from AnalystDesk repository root.', file=sys.stderr)
        return 2
    records = json.loads(manifest.read_text(encoding='utf-8'))
    docs = [r for r in records if r.get('ticker') == 'GOOGL']
    if len(docs) != 3 or len({d.get('report_date') for d in docs}) != 3:
        print('ERROR: expected three distinct Google 10-K filings in original manifest.', file=sys.stderr)
        return 2
    from analyst_desk.document_parsing import process_manifest
    with tempfile.TemporaryDirectory(prefix='analystdesk_google_pagination_') as temp:
        mpath = Path(temp) / 'manifest.json'
        mpath.write_text(json.dumps(docs), encoding='utf-8')
        passages, summaries = process_manifest(str(mpath), cache_root=str(root / 'data' / 'edgar_cache'), max_chars=2400)
    faulty = [p for p in passages if not isinstance(p.get('text'), str)
              or len(p['text'].strip()) < 10 or '\ufffd' in p['text']]
    page_marks = [p for p in faulty if standalone_item8_page_number(p)]
    other = [p for p in faulty if not standalone_item8_page_number(p)]
    print('GOOGL preflight:')
    print('  filings parsed:', len(summaries))
    print('  original passages:', len(passages))
    print('  previously rejected passages:', len(faulty))
    print('  safe standalone Item 8 non-table page labels:', len(page_marks))
    print('  other invalid passages:', len(other))
    print('  page-label counts by filing:', dict(sorted(Counter(p['report_date'] for p in page_marks).items())))
    for p in other[:12]:
        print('  UNSUPPORTED:', p.get('report_date'), p.get('item'), p.get('passage_id'),
              'is_table=', p.get('is_table'), 'text=',repr(str(p.get('text'))[:90]))
    if other:
        print('FAIL CLOSED: other short/corrupt passages remain; do not expect Google to pass.', file=sys.stderr)
        return 2
    if not page_marks:
        print('WARNING: no page markers found; investigate before rerunning selector.', file=sys.stderr)
        return 2
    print('PASS: all excluded short passages are non-table standalone Item 8 page labels.')
    print('READ ONLY: existing SEC files, corpora, indexes and releases unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

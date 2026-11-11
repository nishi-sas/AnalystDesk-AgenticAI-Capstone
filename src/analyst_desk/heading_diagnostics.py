"""Offline, bounded report of potential SEC Item-heading text; read-only."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from analyst_desk.document_parsing import html_blocks, heading_candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    cache_root = Path(args.cache).resolve()
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    for meta in manifest:
        path = Path(meta['local_path']).resolve()
        if not path.is_relative_to(cache_root):
            raise ValueError('Manifest path escapes SEC cache')
        blocks = html_blocks(path.read_bytes())
        recognized = heading_candidates(blocks)
        print(f"=== {meta['ticker']} {meta['report_date']} | blocks={len(blocks)} ===")
        print('Recognized headings:', recognized[:60])
        hits = []
        for i, b in enumerate(blocks):
            if b.kind != 'text' or len(b.text) > 175:
                continue
            if re.match(r'^\s*item\s*(?:1a|1b|1c|7a|7|8|9a|9)', b.text, re.I) or \
               re.match(r'^\s*(?:ris\s*k\s*factors|financial\s*statements|fin\s*ancial)', b.text, re.I):
                hits.append(i)
        # Print a bounded number of compact matches, with preceding/following lines.
        for i in hits[:65]:
            print(f"  [{i:04d}] " + ' || '.join(
                f'{j} {blocks[j].kind}: {blocks[j].text[:130]!r}'
                for j in range(max(0, i-1), min(len(blocks), i+3))
            ))

if __name__ == '__main__':
    main()

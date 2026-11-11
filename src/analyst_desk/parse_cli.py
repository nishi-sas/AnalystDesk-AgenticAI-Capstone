"""Parse locally cached SEC 10-K HTML into section-specific, citable JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analyst_desk.document_parsing import DocumentParseError, process_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline 10-K Item 1A/7/8 extraction")
    parser.add_argument("--manifest", default="evidence/10k_html_manifest.json")
    parser.add_argument("--cache", default="data/edgar_cache")
    parser.add_argument("--output", default="data/parsed/10k_passages.jsonl")
    parser.add_argument("--summary", default="evidence/07_stage2b_summary.json")
    parser.add_argument("--max-chars", type=int, default=2400)
    args = parser.parse_args(argv)
    try:
        passages, summaries = process_manifest(args.manifest, cache_root=args.cache,
                                               max_chars=args.max_chars)
        target, summary = Path(args.output), Path(args.summary)
        target.parent.mkdir(parents=True, exist_ok=True)
        summary.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in passages),
                        encoding="utf-8")
        temp.replace(target)
        summary.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        for s in summaries:
            counts = ", ".join(f"Item {item}: {d['characters']:,} chars, {d['tables']} tables"
                               for item, d in s["sections"].items())
            print(f"{s['ticker']} {s['report_date']}: {s['passage_count']} passages; {counts}")
        print(f"Passages: {target} ({len(passages)} total)")
        print(f"Summary: {summary}")
        return 0
    except (DocumentParseError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

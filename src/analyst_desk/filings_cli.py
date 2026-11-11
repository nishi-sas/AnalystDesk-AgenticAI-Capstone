"""Download exact 10-K HTML source files; Stage 2A CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from analyst_desk.filing_documents import download_filing_html
from analyst_desk.sec_client import EdgarClient, EdgarError


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Download source SEC 10-K HTML with provenance")
    parser.add_argument("--tickers", nargs="+", default=["MSFT", "GOOGL"])
    parser.add_argument("--years", type=int, default=1)
    parser.add_argument("--cache", default="data/edgar_cache")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--manifest", default="evidence/10k_html_manifest.json")
    args = parser.parse_args(argv)
    if args.years < 1:
        parser.error("--years must be >= 1")
    try:
        records = []
        with EdgarClient(cache_dir=args.cache, offline=args.offline) as sec:
            for ticker in args.tickers:
                filings = sec.annual_filings(ticker, years=args.years)
                for filing in filings:
                    path, meta = download_filing_html(sec, filing)
                    records.append({"local_path": str(path), **meta})
                    action = "cached" if meta["cache_hit"] else "downloaded"
                    print(f"{filing.ticker} {filing.report_date}: {action}, {meta['bytes']:,} bytes; {path}")
        target = Path(args.manifest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"Manifest: {target}; documents: {len(records)}")
        return 0
    except (EdgarError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

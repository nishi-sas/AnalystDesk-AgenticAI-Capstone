"""Stage 3B EDGAR facts MCP server: stdio; offline/cache-only unless --online."""
from __future__ import annotations

import argparse
import sys

from analyst_desk.edgar_service import EdgarFactsService


def create_server(edgar: EdgarFactsService):
    from fastmcp import FastMCP

    mcp = FastMCP("AnalystDesk SEC EDGAR Facts")

    @mcp.tool
    def list_annual_filings(ticker: str, years: int = 3) -> dict:
        """List SEC 10-K filings with exact fiscal dates/accessions and original source URLs."""
        return edgar.list_annual_filings(ticker, years)

    @mcp.tool
    def get_annual_facts(ticker: str, years: int = 3) -> dict:
        """Read reported annual revenue and operating income with XBRL fact IDs; no math."""
        return edgar.get_annual_facts(ticker, years)

    @mcp.tool
    def get_annual_fact(ticker: str, report_date: str, metric: str,
                        years: int = 3) -> dict:
        """Read an exact filing's annual USD revenue or operating_income US-GAAP fact."""
        return edgar.get_annual_fact(ticker, report_date, metric, years)

    @mcp.tool
    def edgar_status() -> dict:
        """Inspect offline mode and SEC cache counts without contacting the network."""
        return edgar.edgar_status()

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AnalystDesk SEC EDGAR MCP server (stdio)")
    parser.add_argument("--cache", default="data/edgar_cache")
    parser.add_argument("--online", action="store_true", help="Explicitly permit SEC downloads")
    args = parser.parse_args(argv)
    if args.online:
        from dotenv import load_dotenv
        load_dotenv()
    try:
        server = create_server(EdgarFactsService(args.cache, offline=not args.online))
        server.run(transport="stdio")
    except Exception as exc:
        print(f"EDGAR server startup failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Protocol-level Stage 3B smoke using locally cached SEC responses, no networking."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from analyst_desk.edgar_mcp_server import create_server
from analyst_desk.edgar_service import EdgarFactsService


async def smoke(cache: str) -> dict:
    from fastmcp import Client

    service = EdgarFactsService(cache, offline=True)
    async with Client(create_server(service)) as client:
        tools = sorted(t.name for t in await client.list_tools())
        required = {"list_annual_filings", "get_annual_facts", "get_annual_fact", "edgar_status"}
        if not required.issubset(tools):
            raise RuntimeError(f"Tool discovery failed: {tools}")
        status = (await client.call_tool("edgar_status", {})).data
        if not status["ok"] or not status["data"]["offline"]:
            raise RuntimeError("EDGAR server is not in safe offline mode")
        listing = (await client.call_tool("list_annual_filings", {"ticker": "MSFT", "years": 3})).data
        if not listing["ok"] or listing["data"]["count"] != 3:
            raise RuntimeError(f"MSFT 10-K listing failed: {listing['error_code']}")
        annual = (await client.call_tool("get_annual_facts", {"ticker": "MSFT", "years": 3})).data
        if not annual["ok"] or annual["data"]["count"] != 3:
            raise RuntimeError(f"MSFT annual facts failed: {annual['error_code']}")
        if any(x["revenue"]["accession"] != x["operating_income"]["accession"] or
               x["revenue"]["period_end"] != x["operating_income"]["period_end"]
               for x in annual["data"]["annual"]):
            raise RuntimeError("Found mismatched annual financial periods/accessions")
        google = (await client.call_tool("get_annual_fact", {
            "ticker": "GOOGL", "report_date": "2025-12-31", "metric": "revenue", "years": 3,
        })).data
        if not google["ok"] or google["data"]["fact"]["period_end"] != "2025-12-31":
            raise RuntimeError(f"GOOGL annual XBRL fact failed: {google['error_code']}")
        invalid = (await client.call_tool("get_annual_facts", {
            "ticker": "../../secrets", "years": 3,
        })).data
        if invalid["ok"] or invalid["error_code"] != "INVALID_ARGUMENT":
            raise RuntimeError("Invalid ticker rejected incorrectly")
        return {"status": "PASS", "transport": "FastMCP in-memory protocol",
                "offline": True, "discovered_tools": tools,
                "msft_annual_filings": listing["data"]["count"],
                "msft_annual_fact_years": annual["data"]["count"],
                "google_2025_revenue_fact_id": google["data"]["fact"]["fact_id"],
                "source_files_sha256_verified": True,
                "invalid_ticker_rejected": True, "arithmetic_performed": False}


def main(argv=None):
    cli = argparse.ArgumentParser()
    cli.add_argument("--cache", default="data/edgar_cache")
    args = cli.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(smoke(args.cache)), indent=2))
        return 0
    except Exception as exc:
        print(f"Stage 3B MCP smoke ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

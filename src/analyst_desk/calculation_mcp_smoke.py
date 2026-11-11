"""Stage 3C live cached-SEC/worker/FastMCP protocol smoke, no networking."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from analyst_desk.calculation_service import CalculationService
from analyst_desk.calculation_mcp_server import create_server


async def smoke(cache: str) -> dict:
    from fastmcp import Client

    async with Client(create_server(CalculationService(cache))) as client:
        tools = sorted(t.name for t in await client.list_tools())
        if tools != ["calc_status", "calculate_operating_margin", "calculate_revenue_growth"]:
            raise RuntimeError("Calculation tool discovery mismatch")
        status = (await client.call_tool("calc_status", {})).data
        if not status["ok"] or not status["data"]["offline_verified_source"]:
            raise RuntimeError("Calculator not offline")
        if status["data"]["arbitrary_code_allowed"] or status["data"]["os_hardened_sandbox"]:
            raise RuntimeError("Calculator security reporting is wrong")
        msft = (await client.call_tool("calculate_operating_margin", {
            "ticker": "MSFT", "report_date": "2026-06-30"})).data
        if not msft["ok"] or msft["data"]["value_percent"] != "46.78":
            raise RuntimeError(f"Microsoft margin failed: {msft}")
        googl = (await client.call_tool("calculate_operating_margin", {
            "ticker": "GOOGL", "report_date": "2025-12-31"})).data
        if not googl["ok"] or googl["data"]["value_percent"] != "32.03":
            raise RuntimeError(f"Alphabet margin failed: {googl}")
        growth = (await client.call_tool("calculate_revenue_growth", {
            "ticker": "MSFT", "current_report_date": "2026-06-30",
            "prior_report_date": "2025-06-30"})).data
        if not growth["ok"] or not growth["data"]["operands"]:
            raise RuntimeError(f"Year-on-year growth failed: {growth}")
        invalid = (await client.call_tool("calculate_operating_margin", {
            "ticker": "../../.env", "report_date": "2026-06-30"})).data
        if invalid["ok"] or invalid["error_code"] != "INVALID_ARGUMENT":
            raise RuntimeError("Invalid ticker was not rejected")
        nonadjacent = (await client.call_tool("calculate_revenue_growth", {
            "ticker": "MSFT", "current_report_date": "2026-06-30",
            "prior_report_date": "2024-06-30"})).data
        if nonadjacent["ok"] or nonadjacent["error_code"] != "INVALID_ARGUMENT":
            raise RuntimeError("Nonadjacent fiscal years not rejected")
        return {"status": "PASS", "transport": "FastMCP in-memory protocol",
                "discovered_tools": tools, "verified_sec_offline": True,
                "msft_2026_operating_margin_percent": msft["data"]["value_percent"],
                "googl_2025_operating_margin_percent": googl["data"]["value_percent"],
                "msft_2026_yoy_revenue_growth_percent": growth["data"]["value_percent"],
                "operands_have_sec_fact_ids": all("|us-gaap:" in x for x in growth["data"]["operands"]),
                "worker_separate_process": msft["data"]["execution"]["separate_process"],
                "invalid_ticker_rejected": True, "nonadjacent_year_rejected": True,
                "arbitrary_code_executed": False, "hardened_os_sandbox_claimed": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default="data/edgar_cache")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(smoke(args.cache)), indent=2))
        return 0
    except Exception as exc:
        print(f"Stage 3C smoke ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only smoke test of the opt-in verified profile and in-memory MCP gateway."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--ticker", default="TGT")
    parser.add_argument("--item", default="7")
    args = parser.parse_args()
    os.environ["ANALYSTDESK_VERIFIED_RELEASE_ID"] = args.release_id

    from analyst_desk.stage4a_config import load_planner_settings
    from analyst_desk.verified_runtime_profile import load_verified_profile
    from analyst_desk.stage4b_cli import MCPResearchGateway

    root = Path(__file__).resolve().parents[1]
    profile = load_verified_profile(root)
    settings = load_planner_settings(root)
    assert profile is not None and settings.allowed_tickers == profile.tickers
    assert args.ticker in profile.tickers, "Ticker not allowed in this release"
    print(f"PINNED: {profile.release_id} | companies={len(profile.tickers)} | passages={profile.passages}")
    print("PLANNER ALLOWLIST:", ", ".join(settings.allowed_tickers))

    async def smoke():
        async with MCPResearchGateway(root) as gateway:
            tools = gateway._tools
            if "search_passages" not in tools or "list_annual_filings" not in tools:
                raise RuntimeError("MCP gateway missing required tools")
            # Uses the regular MCP client protocol. This is a configuration smoke test,
            # not a substitute for approved-plan/role-permission integration tests.
            result = await gateway._clients["kb"].call_tool("search_passages", {
                "query": "operating margin revenue inventory expenses",
                "ticker": args.ticker,
                "item": args.item,
                "top_n": 2,
                "rerank": False,
            })
            data = result.data
            if not isinstance(data, dict) or not data.get("ok") or not data.get("data"):
                raise RuntimeError("MCP search failed: " + str(data)[:400])
            hits = data["data"].get("hits", [])
            if not hits or any(h["ticker"] != args.ticker or h["item"] != args.item for h in hits):
                raise RuntimeError("MCP search did not respect company/item filters")
            print("MCP TOOLS REGISTERED:", len(tools))
            print("MCP FILTERED SEARCH PASS:", [h["passage_id"] for h in hits])
    asyncio.run(smoke())
    print("PASS: local expanded planner settings + in-memory MCP source routing")
    print("NOTE: Approval, EDGAR financial facts, Docker and Chainlit still require end-to-end validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run actual in-memory MCP tool calls without launching a network listener."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from analyst_desk.kb_mcp_server import create_server
from analyst_desk.kb_service import FilingsKnowledgeBase


async def run_smoke(corpus: str, index: str, *, rerank: bool) -> dict:
    from fastmcp import Client

    kb = FilingsKnowledgeBase(corpus=corpus, index_dir=index)
    async with Client(create_server(kb)) as client:
        discovered = sorted(t.name for t in await client.list_tools())
        required = {"search_passages", "get_passage", "get_item_sections", "kb_status"}
        if not required.issubset(discovered):
            raise RuntimeError(f"MCP discovery incomplete: {discovered}")
        status_result = await client.call_tool("kb_status", {})
        status = status_result.data
        if not status["ok"] or status["data"]["passage_count"] < 1:
            raise RuntimeError("kb_status failed")
        results = await client.call_tool("search_passages", {
            "query": "What cybersecurity risks does Microsoft disclose?",
            "ticker": "MSFT", "item": "1A", "top_n": 5, "rerank": rerank,
        })
        search = results.data
        if not search["ok"] or not search["data"]["hits"]:
            raise RuntimeError("No MSFT cybersecurity evidence returned")
        if any(x["ticker"] != "MSFT" or x["item"] != "1A"
               for x in search["data"]["hits"]):
            raise RuntimeError("Tool returned evidence outside requested filters")
        pid = search["data"]["hits"][0]["passage_id"]
        passage_result = await client.call_tool("get_passage", {"passage_id": pid})
        passage = passage_result.data
        if not passage["ok"] or passage["data"]["passage_id"] != pid:
            raise RuntimeError("Canonical passage could not be recovered")
        section_result = await client.call_tool("get_item_sections", {
            "ticker": "MSFT", "item": "1A", "limit": 2,
        })
        section = section_result.data
        if not section["ok"] or len(section["data"]["passages"]) != 2:
            raise RuntimeError("Item 1A section pagination failed")
        rejected_result = await client.call_tool("get_passage", {"passage_id": "../../.env"})
        rejected = rejected_result.data
        if rejected["ok"] or rejected["error_code"] != "INVALID_ARGUMENT":
            raise RuntimeError("Unsafe passage ID was not rejected")
        return {"status": "PASS", "transport": "FastMCP in-memory protocol",
                "discovered_tools": discovered,
                "passages_indexed": status["data"]["passage_count"],
                "search_hits": len(search["data"]["hits"]), "first_passage_id": pid,
                "section_total": section["data"]["total_passages"],
                "invalid_path_rejected": True, "reranked": rerank,
                "source_url": passage["data"]["source_url"]}


def main(argv=None) -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--corpus", default="data/parsed/10k_passages.jsonl")
    cli.add_argument("--index", default="data/retrieval_index")
    cli.add_argument("--no-rerank", action="store_true")
    args = cli.parse_args(argv)
    try:
        report = asyncio.run(run_smoke(args.corpus, args.index, rerank=not args.no_rerank))
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f"MCP smoke test ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

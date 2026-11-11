"""Interactive Stage 3D demo helper; prepares/publishes through real MCP calls.

The approval step is deliberately NOT available here; run portal_review_cli separately.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from analyst_desk.portal_service import PortalService
from analyst_desk.portal_mcp_server import create_server

DEMO_SOURCE = "MSFT_2026-06-30_Item1A_00011"


async def do_command(action: str, db: str, public_key: str, report_id: str | None) -> dict:
    from fastmcp import Client
    svc = PortalService(db, public_key)
    async with Client(create_server(svc)) as client:
        if action == "prepare":
            draft = (await client.call_tool("create_report_draft", {
                "title": "Stage 3D approval-gate demonstration — not a research conclusion",
                "markdown": "# Approval workflow demonstration\n\n"
                            "This is a synthetic workflow test. The source ID is used to exercise "
                            "the evidence-reference field; this demonstration makes no substantive financial claim.",
                "source_ids": [DEMO_SOURCE], "open_blockers": []})).data
            if not draft["ok"]:
                raise RuntimeError(str(draft))
            rid, rev = draft["data"]["report_id"], draft["data"]["revision"]
            pending = (await client.call_tool("submit_for_review", {
                "report_id": rid, "expected_revision": rev})).data
            if not pending["ok"]:
                raise RuntimeError(str(pending))
            return {"status": "PENDING_HUMAN_REVIEW", "report_id": rid,
                    "revision": rev, "body_sha256": pending["data"]["body_sha256"],
                    "next": "Run python -m analyst_desk.portal_review_cli review --report-id "
                            + rid + ' --reviewer "Analyst" --decision APPROVE'}
        if action == "publish":
            if not report_id:
                raise RuntimeError("--report-id required")
            record = (await client.call_tool("get_report", {"report_id": report_id})).data
            if not record["ok"]:
                raise RuntimeError(str(record))
            published = (await client.call_tool("publish_report", {
                "report_id": report_id,
                "expected_sha256": record["data"]["body_sha256"]})).data
            if not published["ok"]:
                raise RuntimeError(str(published))
            return {"status": "PASS", "publication": published["data"],
                    "approval_provenance": "separately signed reviewer receipt",
                    "external_publication": False}
    raise RuntimeError("Unknown action")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stage 3D hand-off: prepare/release via MCP; sign off via separate CLI")
    parser.add_argument("action", choices=["prepare", "publish"])
    parser.add_argument("--report-id", default=None)
    parser.add_argument("--db", default="data/research_portal/portal.sqlite3")
    parser.add_argument("--public-key", default="data/research_portal/reviewer_public.pem")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(do_command(args.action, args.db, args.public_key,
                                               args.report_id)), indent=2))
        return 0
    except Exception as exc:
        print("HITL demo ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

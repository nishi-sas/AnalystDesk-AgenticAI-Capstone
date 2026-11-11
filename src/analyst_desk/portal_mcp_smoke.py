"""Full protocol smoke with synthetic human signature, NOT a real analyst review."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from analyst_desk.portal_service import PortalService
from analyst_desk.portal_mcp_server import create_server

SOURCE = "MSFT_2026-06-30_Item1A_00011"


async def smoke():
    from fastmcp import Client
    with tempfile.TemporaryDirectory(prefix="analystdesk_stage3d_") as tmp:
        root = Path(tmp)
        private = Ed25519PrivateKey.generate()  # Test-only synthetic review signer.
        pub = root / "trusted_reviewer.pem"
        pub.write_bytes(private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo))
        portal = PortalService(root / "portal.sqlite3", pub)
        async with Client(create_server(portal)) as client:
            tools = sorted(t.name for t in await client.list_tools())
            expected = sorted(["create_report_draft", "revise_report_draft", "submit_for_review",
                               "get_report", "list_reports", "publish_report", "portal_status"])
            if tools != expected or any("approv" in name for name in tools):
                raise RuntimeError("Unsafe MCP tool surface")
            new = (await client.call_tool("create_report_draft", {
                "title": "Microsoft risk assessment", "markdown": "Draft; do not publish without review.",
                "source_ids": [SOURCE]})).data
            assert new["ok"], new
            rid, body_hash = new["data"]["report_id"], new["data"]["body_sha256"]
            premature = (await client.call_tool("publish_report", {
                "report_id": rid, "expected_sha256": body_hash})).data
            assert not premature["ok"] and premature["error_code"] == "APPROVAL_REQUIRED"
            submit = (await client.call_tool("submit_for_review", {
                "report_id": rid, "expected_revision": 1})).data
            assert submit["ok"], submit
            still = (await client.call_tool("publish_report", {
                "report_id": rid, "expected_sha256": body_hash})).data
            assert not still["ok"]
            result = portal.record_signed_review(rid, "TEST-SIGNER-NOT-HUMAN", "APPROVE", private)
            assert result["ok"], result
            final = (await client.call_tool("publish_report", {
                "report_id": rid, "expected_sha256": body_hash})).data
            assert final["ok"] and final["data"]["status"] == "PUBLISHED", final
            tamper = (await client.call_tool("revise_report_draft", {
                "report_id": rid, "expected_revision": 1, "markdown": "Changed after publish",
                "source_ids": [SOURCE]})).data
            assert not tamper["ok"]
            status = (await client.call_tool("portal_status", {})).data
            assert status["ok"] and status["data"]["reports_by_status"]["PUBLISHED"] == 1
            return {"status": "PASS", "transport": "FastMCP in-memory protocol",
                    "discovered_tools": tools, "agent_mcp_approval_tool_exposed": False,
                    "publish_before_approval_blocked": True,
                    "signed_exact_revision_required": True,
                    "post_publish_edit_blocked": True,
                    "local_publication": True, "external_publication": False,
                    "human_approval_performed": False,
                    "signer": "synthetic_test_key_not_human"}


def main() -> int:
    import sys
    try:
        print(json.dumps(asyncio.run(smoke()), indent=2))
        return 0
    except Exception as exc:
        print("Stage 3D smoke ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

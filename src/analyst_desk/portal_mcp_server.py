"""Stage 3D agent-facing research portal (stdio); no approval endpoint."""
from __future__ import annotations
import argparse
import sys
from analyst_desk.portal_service import PortalService


def create_server(portal: PortalService):
    from fastmcp import FastMCP
    mcp = FastMCP("AnalystDesk Research Portal")

    @mcp.tool
    def create_report_draft(title: str, markdown: str, source_ids: list[str],
                            open_blockers: list[str] | None = None) -> dict:
        """Create a local draft, with SEC evidence IDs and declared unresolved findings."""
        return portal.create_report_draft(title, markdown, source_ids, open_blockers)

    @mcp.tool
    def revise_report_draft(report_id: str, expected_revision: int, markdown: str,
                            source_ids: list[str], open_blockers: list[str] | None = None) -> dict:
        """Create a new immutable draft revision. Any previous approval is invalidated."""
        return portal.revise_report_draft(report_id, expected_revision, markdown, source_ids, open_blockers)

    @mcp.tool
    def submit_for_review(report_id: str, expected_revision: int) -> dict:
        """Request external analyst signoff; does not grant approval."""
        return portal.submit_for_review(report_id, expected_revision)

    @mcp.tool
    def get_report(report_id: str) -> dict:
        """Get complete current report, evidence IDs, blockers, SHA-256, and status."""
        return portal.get_report(report_id)

    @mcp.tool
    def list_reports(status: str = "", limit: int = 20) -> dict:
        """List report metadata by review/publication state."""
        return portal.list_reports(status, limit)

    @mcp.tool
    def publish_report(report_id: str, expected_sha256: str) -> dict:
        """Finalize locally only if the current revision has a valid signed human approval."""
        return portal.publish_report(report_id, expected_sha256)

    @mcp.tool
    def portal_status() -> dict:
        """Show local portal counts and limits; no network publication."""
        return portal.portal_status()

    return mcp


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AnalystDesk research portal MCP server (stdio)")
    parser.add_argument("--db", default="data/research_portal/portal.sqlite3")
    parser.add_argument("--public-key", default="data/research_portal/reviewer_public.pem")
    args = parser.parse_args(argv)
    try:
        create_server(PortalService(args.db, args.public_key)).run(transport="stdio")
    except Exception as exc:
        print("Portal MCP startup failed: " + type(exc).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

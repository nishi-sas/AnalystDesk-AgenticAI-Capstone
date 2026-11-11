"""Stage 3D signed HITL and local publication gate regression tests."""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from analyst_desk.portal_service import PortalService

SRC = "MSFT_2026-06-30_Item1A_00011"
FACT = "CIK0001652044|0001652044-26-000018|us-gaap:Revenues|2025-01-01:2025-12-31|USD"


@pytest.fixture
def ready(tmp_path):
    secret = Ed25519PrivateKey.generate()
    public_path = tmp_path / "trusted.pem"
    public_path.write_bytes(secret.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    service = PortalService(tmp_path / "portal.sqlite3", public_path)
    return service, secret


def draft(svc, blockers=None):
    result = svc.create_report_draft("Company comparison", "## Findings\nSource: [1]", [SRC, FACT], blockers)
    assert result["ok"], result
    return result["data"]


def approve(svc, key, report_id):
    data = svc.get_report(report_id)["data"]
    submitted = svc.submit_for_review(report_id, data["revision"])
    assert submitted["ok"], submitted
    signed = svc.record_signed_review(report_id, "Human reviewer", "APPROVE", key)
    assert signed["ok"], signed
    return signed


def test_create_get_and_source_hashes(ready):
    svc, _ = ready
    d = draft(svc)
    assert d["revision"] == 1 and d["status"] == "DRAFT"
    assert len(d["body_sha256"]) == len(d["sources_sha256"]) == 64
    assert svc.get_report(d["report_id"])["data"]["source_ids"] == [SRC, FACT]


@pytest.mark.parametrize("title,markdown,sources,blockers", [
    ("", "hello", [SRC], []),
    ("Title", "", [SRC], []),
    ("Title", "text", [], []),
    ("Title", "text", ["../../.env"], []),
    ("Title", "text", ["NOT-A-SEC-FACT-ID"], []),
    ("Title", "text", [SRC, SRC], []),
    ("Title", "text", [SRC], ["x" * 501]),
    ("Title", "text", [SRC], "not a list"),
    ("Title", "text", [SRC], ["pending", None]),
])
def test_invalid_drafts_fail_closed(ready, title, markdown, sources, blockers):
    svc, _ = ready
    result = svc.create_report_draft(title, markdown, sources, blockers)
    assert result["ok"] is False and result["error_code"] == "INVALID_ARGUMENT"


def test_preapproval_publish_rejected(ready):
    svc, _ = ready
    d = draft(svc)
    rejected = svc.publish_report(d["report_id"], d["body_sha256"])
    assert rejected["error_code"] == "APPROVAL_REQUIRED"


def test_review_request_is_not_approval(ready):
    svc, _ = ready
    d = draft(svc)
    assert svc.submit_for_review(d["report_id"], 1)["ok"]
    assert svc.get_report(d["report_id"])["data"]["status"] == "IN_REVIEW"
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"] is False


def test_signed_approval_allows_local_publication(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    pub = svc.publish_report(d["report_id"], d["body_sha256"])
    assert pub["ok"] and pub["data"]["destination"] == "local_portal_database"
    assert svc.get_report(d["report_id"])["data"]["publication"] is not None
    assert svc.portal_status()["data"]["external_publication"] is False


def test_revision_invalidates_previous_approval(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    changed = svc.revise_report_draft(d["report_id"], 1, "## corrected finding", [SRC])
    assert changed["ok"] and changed["data"]["status"] == "DRAFT"
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"] is False
    assert svc.publish_report(d["report_id"], changed["data"]["body_sha256"])["ok"] is False
    assert changed["data"]["revision"] == 2
    assert svc.get_report(d["report_id"])["data"]["source_ids"] == [SRC]


def test_stale_revision_blocked(ready):
    svc, _ = ready
    d = draft(svc)
    assert svc.revise_report_draft(d["report_id"], 1, "changed", [SRC])["ok"]
    old = svc.revise_report_draft(d["report_id"], 1, "stale", [SRC])
    assert old["error_code"] == "VERSION_CONFLICT"
    assert svc.submit_for_review(d["report_id"], 1)["error_code"] == "VERSION_CONFLICT"


def test_open_blockers_prevent_review_and_publish(ready):
    svc, _ = ready
    d = draft(svc, ["Unverified ratio"]) 
    sub = svc.submit_for_review(d["report_id"], 1)
    assert sub["error_code"] == "OPEN_BLOCKERS"


def test_rejection_requires_revision_then_resubmission(ready):
    svc, key = ready
    d = draft(svc)
    assert svc.submit_for_review(d["report_id"], 1)["ok"]
    assert svc.record_signed_review(d["report_id"], "Reviewer", "REJECT", key)["ok"]
    assert svc.get_report(d["report_id"])["data"]["status"] == "REJECTED"
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"] is False
    assert svc.revise_report_draft(d["report_id"], 1, "corrected", [SRC])["ok"]
    assert svc.submit_for_review(d["report_id"], 2)["ok"]


def test_reviewer_wrong_key_cannot_sign(ready):
    svc, _ = ready
    d = draft(svc)
    assert svc.submit_for_review(d["report_id"], 1)["ok"]
    res = svc.record_signed_review(d["report_id"], "Mallory", "APPROVE", Ed25519PrivateKey.generate())
    assert res["error_code"] == "APPROVAL_INVALID"


def test_tampered_signature_fails_closed(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE review_receipts SET signature_hex=? WHERE report_id=?", ("00" * 64, d["report_id"]))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_INVALID"


def test_tampered_approval_identity_fails_closed(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE review_receipts SET reviewer='Forged reviewer' WHERE report_id=?", (d["report_id"],))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_INVALID"


def test_tampered_source_ids_without_matching_hash_fails(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE revisions SET source_ids_json='[]' WHERE report_id=?", (d["report_id"],))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "INTEGRITY_ERROR"


def test_tampered_source_ids_with_new_hash_fails_signature(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    from analyst_desk.portal_service import _sha
    source_json = '["GOOGL_2025-12-31_Item1A_00001"]'
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE revisions SET source_ids_json=?,sources_sha256=? WHERE report_id=?",
                     (source_json, _sha(source_json), d["report_id"]))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_INVALID"



def test_title_changed_after_signature_fails(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE reports SET title='Tampered title' WHERE report_id=?", (d["report_id"],))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_INVALID"


def test_blocker_state_changed_after_signature_fails(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE revisions SET blockers_json='[\"danger\"]' WHERE report_id=?", (d["report_id"],))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "INTEGRITY_ERROR"


def test_database_status_change_alone_cannot_publish(ready):
    svc, _ = ready
    d = draft(svc)
    with sqlite3.connect(svc.db_path) as conn:
        conn.execute("UPDATE reports SET status='APPROVED' WHERE report_id=?", (d["report_id"],))
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_REQUIRED"


def test_missing_or_replaced_public_key_blocks_publish(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    svc.public_key_path.unlink()
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_NOT_CONFIGURED"


def test_wrong_expected_report_hash_blocked(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    assert svc.publish_report(d["report_id"], "1" * 64)["error_code"] == "VERSION_CONFLICT"


def test_publish_is_not_repeatable_and_published_immutable(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"]
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"] is False
    assert svc.revise_report_draft(d["report_id"], 1, "text", [SRC])["error_code"] == "INVALID_STATE"


def test_list_reports_status_and_limit(ready):
    svc, _ = ready
    d1, d2 = draft(svc), draft(svc)
    assert svc.submit_for_review(d2["report_id"], 1)["ok"]
    assert len(svc.list_reports("DRAFT")["data"]["reports"]) == 1
    assert len(svc.list_reports("", 1)["data"]["reports"]) == 1
    assert svc.list_reports("APPROVE ME")["error_code"] == "INVALID_ARGUMENT"
    assert svc.list_reports("", True)["error_code"] == "INVALID_ARGUMENT"


def test_ids_and_sql_injection_rejected(ready):
    svc, _ = ready
    for candidate in ("../.env", "a' OR 1=1 --", "g" * 32, "00" * 17):
        assert svc.get_report(candidate)["error_code"] == "INVALID_ARGUMENT"
    assert svc.get_report("0" * 32)["error_code"] == "NOT_FOUND"


def test_audit_and_version_history_persist(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"]
    with sqlite3.connect(svc.db_path) as con:
        events = [r[0] for r in con.execute("SELECT event FROM audit_events ORDER BY event_id")]
        assert events == ["CREATED", "SUBMITTED_FOR_REVIEW", "REVIEW_APPROVE", "PUBLISHED_LOCALLY"]
        assert con.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
    reloaded = PortalService(svc.db_path, svc.public_key_path)
    assert reloaded.get_report(d["report_id"])["data"]["status"] == "PUBLISHED"


def test_mcp_tool_surface_if_fastmcp_installed(ready):
    pytest.importorskip("fastmcp")
    from analyst_desk.portal_mcp_server import create_server
    import asyncio
    from fastmcp import Client
    svc, _ = ready

    async def calls():
        async with Client(create_server(svc)) as client:
            names = sorted(t.name for t in await client.list_tools())
            assert "approve_report" not in names and "record_signed_review" not in names
            assert len(names) == 7
            r = (await client.call_tool("create_report_draft", {
                "title": "Report", "markdown": "Sample", "source_ids": [SRC]})).data
            assert r["ok"]
            before = (await client.call_tool("publish_report", {
                "report_id": r["data"]["report_id"],
                "expected_sha256": r["data"]["body_sha256"]})).data
            assert before["error_code"] == "APPROVAL_REQUIRED"
    asyncio.run(calls())


def test_review_private_key_is_encrypted_and_separate(tmp_path, monkeypatch):
    from analyst_desk.portal_review_cli import initialize_keys
    import getpass
    private_path = tmp_path / "private" / "reviewer_private.pem"
    public_path = tmp_path / "public" / "reviewer_public.pem"
    answers = iter(["long-demo-passphrase-1", "long-demo-passphrase-1"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    initialize_keys(private_path, public_path)
    assert private_path.exists() and public_path.exists()
    assert b"ENCRYPTED PRIVATE KEY" in private_path.read_bytes()
    assert b"PUBLIC KEY" in public_path.read_bytes()
    with pytest.raises(RuntimeError, match="overwrite"):
        initialize_keys(private_path, public_path)


def test_review_cli_refuses_noninteractive_review(tmp_path, monkeypatch):
    from analyst_desk.portal_review_cli import main
    # pytest stdout/stdin are non-TTY, so no agent can pass approval by piping input.
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["review", "--report-id", "a" * 32,
                 "--reviewer", "Agent", "--decision", "APPROVE"]) == 2


def test_previous_approval_not_valid_for_new_revision_even_if_text_is_same(ready):
    svc, key = ready
    d = draft(svc)
    approve(svc, key, d["report_id"])
    changed = svc.revise_report_draft(d["report_id"], 1, d["markdown"], [SRC, FACT])
    assert changed["ok"]
    assert changed["data"]["body_sha256"] == d["body_sha256"]
    assert svc.submit_for_review(d["report_id"], 2)["ok"]
    assert svc.publish_report(d["report_id"], d["body_sha256"])["error_code"] == "APPROVAL_REQUIRED"
    assert svc.record_signed_review(d["report_id"], "Reviewer", "APPROVE", key)["ok"]
    assert svc.publish_report(d["report_id"], d["body_sha256"])["ok"]

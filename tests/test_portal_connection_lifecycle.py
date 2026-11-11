"""Stage 3D Windows regression: connections must close before temp SQLite cleanup."""
from __future__ import annotations
import sqlite3
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from analyst_desk.portal_service import PortalService
import analyst_desk.portal_service as portal_module

SRC = "MSFT_2026-06-30_Item1A_00011"


def test_all_service_connection_handles_closed(tmp_path, monkeypatch):
    """Track actual sqlite connections throughout create -> sign -> publish."""
    private = Ed25519PrivateKey.generate()
    public = tmp_path / "reviewer.pem"
    public.write_bytes(private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    original_connect = sqlite3.connect
    opened = []

    def track(*args, **kwargs):
        con = original_connect(*args, **kwargs)
        opened.append(con)
        return con

    monkeypatch.setattr(portal_module.sqlite3, "connect", track)
    service = PortalService(tmp_path / "portal.sqlite3", public)
    created = service.create_report_draft("Test", "Sample report", [SRC])
    assert created["ok"]
    data = created["data"]
    assert service.get_report(data["report_id"])["ok"]
    assert service.list_reports()["ok"]
    assert service.portal_status()["ok"]
    assert service.submit_for_review(data["report_id"], 1)["ok"]
    assert service.record_signed_review(data["report_id"], "Test reviewer", "APPROVE", private)["ok"]
    assert service.publish_report(data["report_id"], data["body_sha256"])["ok"]
    assert len(opened) >= 8
    for con in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            con.execute("SELECT 1")


def test_failed_transaction_rolls_back_and_closes(tmp_path):
    service = PortalService(tmp_path / "portal.sqlite3", tmp_path / "unused.pem")
    handle = None
    with pytest.raises(RuntimeError, match="forced rollback"):
        with service._connection() as con:
            handle = con
            con.execute("INSERT INTO audit_events(report_id,event,revision,details_json,at) "
                        "VALUES('test', 'SHOULD_NOT_COMMIT', 1, '{}', 'now')")
            raise RuntimeError("forced rollback")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        handle.execute("SELECT 1")
    with service._connection() as con:
        remaining = con.execute("SELECT count(*) FROM audit_events").fetchone()[0]
        assert remaining == 0
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        con.execute("SELECT 1")


def test_connection_closes_after_success(tmp_path):
    service = PortalService(tmp_path / "portal.sqlite3", tmp_path / "unused.pem")
    with service._connection() as con:
        assert con.execute("SELECT count(*) FROM reports").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        con.execute("SELECT 1")

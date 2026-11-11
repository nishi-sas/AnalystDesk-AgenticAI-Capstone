"""Stage 3D: local auditable research portal with signed, revision-bound HITL.

The agent-facing API NEVER signs reviews and cannot read the private review key.
Approval is performed by a separate, interactive reviewer CLI.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PASSAGE = re.compile(r"^[A-Z]{1,10}_\d{4}-\d{2}-\d{2}_Item(?:1A|7|8)_\d{5}$")
_FACT = re.compile(r"^CIK\d{10}\|\d{10}-\d{2}-\d{6}\|us-gaap:[A-Za-z][A-Za-z0-9]*\|\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}\|USD$")
_VALID_STATES = {"DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "PUBLISHED"}
_MAX_BODY = 500_000


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _bad(code: str, message: str) -> dict:
    return {"ok": False, "error_code": code, "message": message}


class PortalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _require(condition: bool, code: str, message: str):
    if not condition:
        raise PortalError(code, message)


def _rid(value: Any) -> str:
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None,
             "INVALID_ARGUMENT", "Invalid report identifier")
    return value


def _revision(value: Any) -> int:
    _require(type(value) is int and 1 <= value <= 10_000, "INVALID_ARGUMENT", "Invalid revision")
    return value


def _text(value: Any, name: str, limit: int) -> str:
    _require(isinstance(value, str) and 0 < len(value.strip()) <= limit,
             "INVALID_ARGUMENT", f"Invalid or empty {name}")
    _require("\x00" not in value, "INVALID_ARGUMENT", f"Invalid {name}")
    return value


def _sources(value: Any) -> list[str]:
    _require(isinstance(value, list) and 1 <= len(value) <= 100,
             "INVALID_ARGUMENT", "Provide 1 to 100 SEC passage/fact identifiers")
    for item in value:
        _require(isinstance(item, str) and (_PASSAGE.fullmatch(item) or _FACT.fullmatch(item)),
                 "INVALID_ARGUMENT", "Source identifier must be an SEC passage ID or exact fact ID")
    _require(len(set(value)) == len(value), "INVALID_ARGUMENT", "Duplicate SEC source IDs")
    return value


def _blockers(value: Any) -> list[str]:
    if value is None:
        return []
    _require(isinstance(value, list) and len(value) <= 50,
             "INVALID_ARGUMENT", "Invalid blockers list")
    for item in value:
        _text(item, "blocker", 500)
    return value


def _signing_message(report_id: str, revision: int, body_sha256: str,
                     sources_sha256: str, title_sha256: str, blockers_sha256: str,
                     decision: str, reviewer: str, decided_at: str, key_fingerprint: str) -> bytes:
    payload = {"context": "AnalystDesk-HITL-review-v1", "report_id": report_id,
               "revision": revision, "body_sha256": body_sha256,
               "sources_sha256": sources_sha256, "title_sha256": title_sha256,
               "blockers_sha256": blockers_sha256, "decision": decision,
               "reviewer": reviewer, "decided_at": decided_at,
               "key_fingerprint": key_fingerprint}
    return _json(payload).encode("utf-8")


def _pubkey_fingerprint(public_key: Any) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return _sha(raw)


class PortalService:
    def __init__(self, db_path: str | Path = "data/research_portal/portal.sqlite3",
                 public_key_path: str | Path = "data/research_portal/reviewer_public.pem"):
        self.db_path = Path(db_path)
        self.public_key_path = Path(public_key_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        """Transactional SQLite connection that ALWAYS closes the file handle.

        sqlite3.Connection's built-in context manager commits/rolls back, but
        does NOT call close(). An unclosed handle prevents TemporaryDirectory
        cleanup of a SQLite database on Windows (WinError 32).
        """
        con = sqlite3.connect(self.db_path, timeout=15)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            try:
                yield con
                con.commit()
            except BaseException:
                con.rollback()
                raise
        finally:
            con.close()

    def _initialize(self):
        with self._connection() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                revision INTEGER NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS revisions (
                report_id TEXT NOT NULL, revision INTEGER NOT NULL,
                markdown TEXT NOT NULL, body_sha256 TEXT NOT NULL,
                source_ids_json TEXT NOT NULL, sources_sha256 TEXT NOT NULL,
                blockers_json TEXT NOT NULL, blockers_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(report_id, revision),
                FOREIGN KEY(report_id) REFERENCES reports(report_id)
            );
            CREATE TABLE IF NOT EXISTS review_receipts (
                receipt_id TEXT PRIMARY KEY, report_id TEXT NOT NULL,
                revision INTEGER NOT NULL, body_sha256 TEXT NOT NULL,
                sources_sha256 TEXT NOT NULL, title_sha256 TEXT NOT NULL,
                blockers_sha256 TEXT NOT NULL, decision TEXT NOT NULL,
                reviewer TEXT NOT NULL, decided_at TEXT NOT NULL,
                key_fingerprint TEXT NOT NULL, signature_hex TEXT NOT NULL,
                FOREIGN KEY(report_id, revision) REFERENCES revisions(report_id, revision)
            );
            CREATE TABLE IF NOT EXISTS publications (
                report_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL, sources_sha256 TEXT NOT NULL,
                receipt_id TEXT NOT NULL, published_at TEXT NOT NULL,
                FOREIGN KEY(report_id) REFERENCES reports(report_id),
                FOREIGN KEY(receipt_id) REFERENCES review_receipts(receipt_id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL, event TEXT NOT NULL,
                revision INTEGER NOT NULL, details_json TEXT NOT NULL,
                at TEXT NOT NULL
            );
            """)

    @staticmethod
    def _audit(con, report_id: str, event: str, revision: int, details: dict):
        con.execute("INSERT INTO audit_events(report_id,event,revision,details_json,at) VALUES(?,?,?,?,?)",
                    (report_id, event, revision, _json(details), _utc()))

    @staticmethod
    def _current(con, report_id: str):
        r = con.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
        _require(r is not None, "NOT_FOUND", "Report not found")
        v = con.execute("SELECT * FROM revisions WHERE report_id=? AND revision=?",
                        (report_id, r["revision"])).fetchone()
        _require(v is not None, "INTEGRITY_ERROR", "Report revision missing")
        _require(_sha(v["markdown"]) == v["body_sha256"],
                 "INTEGRITY_ERROR", "Report content hash mismatch")
        _require(_sha(v["source_ids_json"]) == v["sources_sha256"],
                 "INTEGRITY_ERROR", "SEC evidence hash mismatch")
        _require(_sha(v["blockers_json"]) == v["blockers_sha256"],
                 "INTEGRITY_ERROR", "Open blockers hash mismatch")
        return r, v

    @staticmethod
    def _describe(r, v, include_markdown=True):
        out = {"report_id": r["report_id"], "title": r["title"],
               "revision": r["revision"], "status": r["status"],
               "body_sha256": v["body_sha256"],
               "sources_sha256": v["sources_sha256"],
               "title_sha256": _sha(r["title"]),
               "blockers_sha256": v["blockers_sha256"],
               "source_ids": json.loads(v["source_ids_json"]),
               "open_blockers": json.loads(v["blockers_json"]),
               "created_at": r["created_at"], "updated_at": r["updated_at"]}
        if include_markdown:
            out["markdown"] = v["markdown"]
        return out

    def create_report_draft(self, title: str, markdown: str, source_ids: list[str],
                            open_blockers: list[str] | None = None) -> dict:
        try:
            _text(title, "title", 200)
            _text(markdown, "markdown", _MAX_BODY)
            _sources(source_ids)
            _blockers(open_blockers)
            rid, now = secrets.token_hex(16), _utc()
            sj, bj = _json(source_ids), _json(open_blockers or [])
            with self._connection() as con:
                con.execute("INSERT INTO reports VALUES(?,?,?,?,?,?)",
                            (rid, title, 1, "DRAFT", now, now))
                con.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?)",
                            (rid, 1, markdown, _sha(markdown), sj, _sha(sj), bj, _sha(bj), now))
                self._audit(con, rid, "CREATED", 1, {"sources_count": len(source_ids)})
                r, v = self._current(con, rid)
                return _ok(self._describe(r, v))
        except PortalError as exc:
            return _bad(exc.code, str(exc))

    def revise_report_draft(self, report_id: str, expected_revision: int,
                            markdown: str, source_ids: list[str],
                            open_blockers: list[str] | None = None) -> dict:
        try:
            _rid(report_id)
            _revision(expected_revision)
            _text(markdown, "markdown", _MAX_BODY)
            _sources(source_ids)
            _blockers(open_blockers)
            with self._connection() as con:
                con.execute("BEGIN IMMEDIATE")
                r, _ = self._current(con, report_id)
                _require(r["status"] != "PUBLISHED", "INVALID_STATE", "Published report is immutable")
                _require(r["revision"] == expected_revision,
                         "VERSION_CONFLICT", "Stale report revision")
                new_rev, now = expected_revision + 1, _utc()
                sj, bj = _json(source_ids), _json(open_blockers or [])
                con.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?)",
                            (report_id, new_rev, markdown, _sha(markdown), sj, _sha(sj), bj, _sha(bj), now))
                con.execute("UPDATE reports SET revision=?,status='DRAFT',updated_at=? WHERE report_id=?",
                            (new_rev, now, report_id))
                self._audit(con, report_id, "REVISED", new_rev,
                            {"prior_revision": expected_revision, "prior_approval_invalidated": True})
                r, v = self._current(con, report_id)
                return _ok(self._describe(r, v))
        except PortalError as exc:
            return _bad(exc.code, str(exc))

    def submit_for_review(self, report_id: str, expected_revision: int) -> dict:
        try:
            _rid(report_id)
            _revision(expected_revision)
            with self._connection() as con:
                con.execute("BEGIN IMMEDIATE")
                r, v = self._current(con, report_id)
                _require(r["revision"] == expected_revision,
                         "VERSION_CONFLICT", "Stale report revision")
                _require(r["status"] == "DRAFT", "INVALID_STATE", "Report is not a draft")
                _require(not json.loads(v["blockers_json"]), "OPEN_BLOCKERS",
                         "Resolve all declared blockers before review")
                now = _utc()
                con.execute("UPDATE reports SET status='IN_REVIEW',updated_at=? WHERE report_id=?",
                            (now, report_id))
                self._audit(con, report_id, "SUBMITTED_FOR_REVIEW", expected_revision,
                            {"body_sha256": v["body_sha256"], "sources_sha256": v["sources_sha256"],
                             "title_sha256": _sha(r["title"]), "blockers_sha256": v["blockers_sha256"]})
                return _ok({"report_id": report_id, "revision": expected_revision,
                            "status": "IN_REVIEW", "body_sha256": v["body_sha256"],
                            "sources_sha256": v["sources_sha256"],
                             "title_sha256": _sha(r["title"]), "blockers_sha256": v["blockers_sha256"]})
        except PortalError as exc:
            return _bad(exc.code, str(exc))

    def get_report(self, report_id: str) -> dict:
        try:
            _rid(report_id)
            with self._connection() as con:
                r, v = self._current(con, report_id)
                obj = self._describe(r, v)
                p = con.execute("SELECT revision,body_sha256,published_at FROM publications WHERE report_id=?",
                                (report_id,)).fetchone()
                obj["publication"] = dict(p) if p else None
                return _ok(obj)
        except PortalError as exc:
            return _bad(exc.code, str(exc))

    def list_reports(self, status: str = "", limit: int = 20) -> dict:
        try:
            _require(isinstance(status, str) and (not status or status in _VALID_STATES),
                     "INVALID_ARGUMENT", "Invalid report status filter")
            _require(type(limit) is int and 1 <= limit <= 100,
                     "INVALID_ARGUMENT", "Limit must be 1..100")
            with self._connection() as con:
                rows = con.execute(
                    "SELECT report_id,title,revision,status,updated_at FROM reports "
                    "WHERE (?='' OR status=?) ORDER BY updated_at DESC, report_id LIMIT ?",
                    (status, status, limit)).fetchall()
            return _ok({"reports": [dict(r) for r in rows], "returned": len(rows)})
        except PortalError as exc:
            return _bad(exc.code, str(exc))

    def portal_status(self) -> dict:
        with self._connection() as con:
            counts = {s: con.execute("SELECT COUNT(*) FROM reports WHERE status=?", (s,)).fetchone()[0]
                      for s in sorted(_VALID_STATES)}
        return _ok({"reports_by_status": counts,
                    "local_database_only": True, "external_publication": False,
                    "mcp_approval_tool_exposed": False,
                    "reviewer_public_key_configured": self.public_key_path.is_file(),
                    "approval_requires_valid_signature": True,
                    "human_identity_integrated": False,
                    "compliance_critic_integrated": False,
                    "production_authz_integrated": False})

    def _load_public_key(self):
        _require(self.public_key_path.is_file(), "APPROVAL_NOT_CONFIGURED",
                 "Reviewer public key not configured")
        try:
            key = serialization.load_pem_public_key(self.public_key_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise PortalError("APPROVAL_NOT_CONFIGURED", "Invalid reviewer public key") from exc
        _require(key.__class__.__name__.endswith("Ed25519PublicKey"),
                 "APPROVAL_NOT_CONFIGURED", "Expected Ed25519 reviewer public key")
        return key

    def publish_report(self, report_id: str, expected_sha256: str) -> dict:
        try:
            _rid(report_id)
            _require(isinstance(expected_sha256, str) and _SHA.fullmatch(expected_sha256),
                     "INVALID_ARGUMENT", "Expected report SHA-256 is required")
            with self._connection() as con:
                con.execute("BEGIN IMMEDIATE")
                r, v = self._current(con, report_id)
                _require(r["status"] == "APPROVED", "APPROVAL_REQUIRED", "Human approval required")
                _require(v["body_sha256"] == expected_sha256,
                         "VERSION_CONFLICT", "Report hash differs from requested version")
                _require(not json.loads(v["blockers_json"]), "OPEN_BLOCKERS", "Open blockers prevent publication")
                receipt = con.execute(
                    "SELECT * FROM review_receipts WHERE report_id=? AND revision=? AND decision='APPROVE' "
                    "ORDER BY decided_at DESC LIMIT 1", (report_id, r["revision"])).fetchone()
                _require(receipt is not None, "APPROVAL_REQUIRED", "No approval receipt for current revision")
                _require(receipt["body_sha256"] == v["body_sha256"] and
                         receipt["sources_sha256"] == v["sources_sha256"] and
                         receipt["title_sha256"] == _sha(r["title"]) and
                         receipt["blockers_sha256"] == v["blockers_sha256"],
                         "APPROVAL_INVALID", "Approval does not match current content and sources")
                pub = self._load_public_key()
                _require(receipt["key_fingerprint"] == _pubkey_fingerprint(pub),
                         "APPROVAL_INVALID", "Approval signer fingerprint mismatch")
                message = _signing_message(report_id, r["revision"],
                           receipt["body_sha256"], receipt["sources_sha256"],
                           receipt["title_sha256"], receipt["blockers_sha256"],
                           receipt["decision"], receipt["reviewer"], receipt["decided_at"],
                           receipt["key_fingerprint"])
                try:
                    pub.verify(bytes.fromhex(receipt["signature_hex"]), message)
                except (InvalidSignature, ValueError):
                    raise PortalError("APPROVAL_INVALID", "Approval signature verification failed")
                now = _utc()
                con.execute("INSERT INTO publications VALUES(?,?,?,?,?,?)",
                            (report_id, r["revision"], v["body_sha256"], v["sources_sha256"],
                             receipt["receipt_id"], now))
                con.execute("UPDATE reports SET status='PUBLISHED',updated_at=? WHERE report_id=?",
                            (now, report_id))
                self._audit(con, report_id, "PUBLISHED_LOCALLY", r["revision"],
                            {"receipt_id": receipt["receipt_id"], "body_sha256": v["body_sha256"]})
                return _ok({"report_id": report_id, "revision": r["revision"],
                            "body_sha256": v["body_sha256"], "status": "PUBLISHED",
                            "published_at": now, "destination": "local_portal_database",
                            "external_publication": False})
        except PortalError as exc:
            return _bad(exc.code, str(exc))
        except sqlite3.IntegrityError:
            return _bad("INVALID_STATE", "Publication already recorded")

    def record_signed_review(self, report_id: str, reviewer: str, decision: str,
                             private_key: Ed25519PrivateKey) -> dict:
        """NOT REGISTERED AS MCP TOOL. Restricted to human-review CLI with private key."""
        try:
            _rid(report_id)
            _text(reviewer, "reviewer", 100)
            _require(isinstance(decision, str) and decision in {"APPROVE", "REJECT"},
                     "INVALID_ARGUMENT", "Review decision must be APPROVE or REJECT")
            _require(isinstance(private_key, Ed25519PrivateKey),
                     "INVALID_ARGUMENT", "Ed25519 signing key required")
            pub = self._load_public_key()
            _require(_pubkey_fingerprint(private_key.public_key()) == _pubkey_fingerprint(pub),
                     "APPROVAL_INVALID", "Reviewer private key does not match trusted public key")
            with self._connection() as con:
                con.execute("BEGIN IMMEDIATE")
                r, v = self._current(con, report_id)
                _require(r["status"] == "IN_REVIEW", "INVALID_STATE", "Report not in human review")
                _require(not json.loads(v["blockers_json"]), "OPEN_BLOCKERS", "Open blockers prevent approval")
                at, fingerprint, receipt_id = _utc(), _pubkey_fingerprint(pub), secrets.token_hex(16)
                msg = _signing_message(report_id, r["revision"], v["body_sha256"],
                                       v["sources_sha256"], _sha(r["title"]),
                                       v["blockers_sha256"], decision, reviewer, at, fingerprint)
                signature = private_key.sign(msg).hex()
                con.execute("INSERT INTO review_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (receipt_id, report_id, r["revision"], v["body_sha256"],
                             v["sources_sha256"], _sha(r["title"]), v["blockers_sha256"],
                             decision, reviewer, at, fingerprint, signature))
                con.execute("UPDATE reports SET status=?,updated_at=? WHERE report_id=?",
                            ("APPROVED" if decision == "APPROVE" else "REJECTED", at, report_id))
                self._audit(con, report_id, "REVIEW_" + decision, r["revision"],
                            {"receipt_id": receipt_id, "reviewer": reviewer,
                             "key_fingerprint": fingerprint})
                return _ok({"report_id": report_id, "status": "APPROVED" if decision == "APPROVE" else "REJECTED",
                            "revision": r["revision"], "body_sha256": v["body_sha256"],
                            "reviewer": reviewer, "receipt_id": receipt_id})
        except PortalError as exc:
            return _bad(exc.code, str(exc))

"""Human-side, interactive-only approval CLI. NEVER expose via MCP tools."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from analyst_desk.portal_service import PortalService


def default_private_key() -> Path:
    return Path.home() / ".analystdesk" / "reviewer_private.pem"


def initialize_keys(private_path: Path, public_path: Path):
    if private_path.exists() or public_path.exists():
        raise RuntimeError("Refusing to overwrite existing review keys")
    private_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(_new_key_password()))
    # Encrypt the private key at rest; the reviewer enters their passphrase for each decision.
    try:
        with private_path.open("xb") as handle:
            handle.write(pem)
        if os.name != "nt":
            os.chmod(private_path, 0o600)
        with public_path.open("xb") as handle:
            handle.write(key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo))
    except Exception:
        # Never write a second keypair silently after a partial error.
        raise


def _new_key_password() -> bytes:
    import getpass
    first = getpass.getpass("Create a new review-key passphrase (min 12 chars): ")
    second = getpass.getpass("Repeat passphrase: ")
    if len(first) < 12 or first != second:
        raise RuntimeError("Passphrase mismatch or fewer than 12 characters")
    return first.encode("utf-8")


def load_private_key(path: Path):
    import getpass
    password = getpass.getpass("Review-key passphrase: ").encode("utf-8")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=password)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Cannot unlock reviewer private key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("Not an Ed25519 private key")
    return key


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local analyst review only; no agent approval")
    parser.add_argument("--db", default="data/research_portal/portal.sqlite3")
    parser.add_argument("--public-key", default="data/research_portal/reviewer_public.pem")
    parser.add_argument("--private-key", default=str(default_private_key()))
    cmd = parser.add_subparsers(dest="action", required=True)
    cmd.add_parser("init-keys")
    review = cmd.add_parser("review")
    review.add_argument("--report-id", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--decision", choices=["APPROVE", "REJECT"], required=True)
    args = parser.parse_args(argv)
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("A real interactive terminal is required for key generation/review")
        if args.action == "init-keys":
            initialize_keys(Path(args.private_key), Path(args.public_key))
            print("Reviewer private key stored outside project by default; public key configured.")
            return 0
        portal = PortalService(args.db, args.public_key)
        record = portal.get_report(args.report_id)
        if not record["ok"] or record["data"]["status"] != "IN_REVIEW":
            raise RuntimeError("Report not found or not awaiting review")
        data = record["data"]
        print("\n========= COMPLETE DRAFT FOR REVIEW =========")
        print("Title:", data["title"])
        print("Revision:", data["revision"])
        print("Content SHA-256:", data["body_sha256"])
        print("Source IDs SHA-256:", data["sources_sha256"])
        print("Sources:", json.dumps(data["source_ids"], indent=2))
        print("Open blockers:", json.dumps(data["open_blockers"], indent=2))
        print("\n========= REPORT CONTENT =========")
        print(data["markdown"])
        print("========= END REPORT =========\n")
        expected = args.decision + " " + data["body_sha256"][:12]
        print("Required confirmation:", expected)
        if input("Type confirmation exactly: ").strip() != expected:
            raise RuntimeError("Review not confirmed; no approval recorded")
        key = load_private_key(Path(args.private_key))
        result = portal.record_signed_review(args.report_id, args.reviewer, args.decision, key)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 2
    except Exception as exc:
        print("Review CLI ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

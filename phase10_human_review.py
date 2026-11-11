"""Local-only, explicit human report-review decision and downloadable receipt.

NO portal registration, signed review, publication, model execution or approval
state mutation occurs here.  Chainlit currently has no reviewer authentication;
identities are self-declared and the audit is a local prototype record.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from phase10_bridge import BridgeError, check_thread_id
from phase10_review_bridge import validate_review_bundle

_DECISIONS = frozenset({"APPROVE", "REQUEST_REVISION", "REJECT"})
_ID_RE = re.compile(r"ui_stage4c3_([a-f0-9]{32})_([a-f0-9]{8})_manifest\.json")
_LOCAL_RE = re.compile(r"HR-[a-f0-9]{24}")


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_result(result: dict, *, root: Path) -> dict:
    if not isinstance(result, dict):
        raise BridgeError("No validated Critic review is attached to this session.")
    tid = check_thread_id(result.get("thread_id"))
    manifest_name = result.get("manifest_name")
    if not isinstance(manifest_name, str):
        raise BridgeError("Missing review manifest identity.")
    match = _ID_RE.fullmatch(manifest_name)
    if match is None or match.group(1) != tid:
        raise BridgeError("Review manifest does not match the approved research thread.")
    prefix_name = manifest_name.removesuffix("_manifest.json")
    current = validate_review_bundle(root, tid, prefix_name)
    for field in ("phase", "draft_sha256", "revision_count", "hard_blockers", "critic_review", "ready_for_human_review", "supported", "claim_count"):
        if current.get(field) != result.get(field):
            raise BridgeError("The underlying Critic review has changed. Human decision refused.")
    return current


def local_report_id(result: dict) -> str:
    """Stable *local review ID*, deliberately not a portal report ID."""
    if not isinstance(result, dict):
        raise BridgeError("Missing review result.")
    tid = check_thread_id(result.get("thread_id"))
    name = result.get("manifest_name", "")
    sha = result.get("draft_sha256", "")
    if not isinstance(name, str) or not _ID_RE.fullmatch(name) or not name.startswith(f"ui_stage4c3_{tid}_") or not re.fullmatch(r"[a-f0-9]{64}", str(sha)):
        raise BridgeError("Invalid bound review identity.")
    return "HR-" + hashlib.sha256((tid + "|" + name + "|" + sha).encode()).hexdigest()[:24]


def _store_path(root: Path, report_id: str) -> Path:
    if not isinstance(report_id, str) or not _LOCAL_RE.fullmatch(report_id):
        raise BridgeError("Invalid local review identifier.")
    return root / "docker_runtime" / "human_review_decisions" / (report_id + ".json")


def read_decision(root: Path, result: dict) -> dict | None:
    """Read-only receipt lookup. Invalid/tampered record fails closed."""
    rid = local_report_id(result)
    path = _store_path(root, rid)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 15_000:
            raise ValueError("Receipt too large")
        document = json.loads(path.read_text(encoding="utf-8"))
        digest = document.pop("receipt_sha256")
        expected = hashlib.sha256(_canonical(document)).hexdigest()
        document["receipt_sha256"] = digest
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) or digest != expected:
            raise ValueError("Receipt digest mismatch")
        if (document.get("local_report_id") != rid or
            document.get("thread_id") != result.get("thread_id") or
            document.get("draft_sha256") != result.get("draft_sha256") or
            document.get("manifest_name") != result.get("manifest_name") or
            document.get("decision") not in _DECISIONS or
            document.get("approval_scope") != "LOCAL_CHAINLIT_DEMO_ONLY"):
            raise ValueError("Receipt binding mismatch")
        return document
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BridgeError("Human decision record is missing fields or failed its integrity check.") from exc


def can_approve(result: dict) -> bool:
    review = result.get("critic_review") if isinstance(result, dict) else None
    findings = review.get("findings") if isinstance(review, dict) else None
    return bool(
        result.get("ready_for_human_review") is True
        and result.get("phase") == "STAGE4C_READY_FOR_HUMAN_REVIEW"
        and result.get("hard_blockers") == []
        and isinstance(findings, list) and len(findings) > 0
        and all(isinstance(f, dict) and f.get("verdict") == "SUPPORTED" for f in findings)
        and result.get("supported") == result.get("claim_count") == len(findings)
        and review.get("model_semantic_assessment_performed") is True
        and review.get("critic_review_performed") is True
        and review.get("human_report_approved") is False
        and review.get("publication_performed") is False
    )


def _one_line(s: str, field: str, maximum: int) -> str:
    if not isinstance(s, str) or not (2 <= len(s.strip()) <= maximum) or any(ord(x) < 32 or ord(x) == 127 for x in s):
        raise BridgeError(f"{field} must be plain, single-line text (2–{maximum} characters).")
    return s.strip()


def parse_confirmation(text: str, decision: str) -> tuple[str, str]:
    """Require an explicit confirmation phrase; never approve on a button click alone."""
    if decision not in _DECISIONS or not isinstance(text, str):
        raise BridgeError("Invalid human-review confirmation.")
    fields = [f.strip() for f in text.split("|", 2)]
    if len(fields) != 3 or fields[0] != decision or text != text.lstrip():
        raise BridgeError(f"Confirm using: {decision} | Your Name | Your review note")
    reviewer = _one_line(fields[1], "Reviewer name", 100)
    note = _one_line(fields[2], "Review note", 1000)
    return reviewer, note


def record_decision(root: Path, result: dict, decision: str, reviewer: str, note: str) -> dict:
    if decision not in _DECISIONS:
        raise BridgeError("Unrecognized human report decision.")
    current = _verify_result(result, root=root)
    rid = local_report_id(current)
    if decision == "APPROVE" and not can_approve(current):
        raise BridgeError("Report approval refused: Critic findings are blocked or incomplete.")
    reviewer = _one_line(reviewer, "Reviewer name", 100)
    note = _one_line(note, "Review note", 1000)
    record = {
        "local_report_id": rid, "thread_id": current["thread_id"],
        "manifest_name": current["manifest_name"],
        "draft_sha256": current["draft_sha256"],
        "critic_review_sha256": hashlib.sha256(_canonical(current["critic_review"])).hexdigest(),
        "critic_phase": current["phase"], "revision_count": current["revision_count"],
        "critic_supported": current["supported"], "critic_claim_count": current["claim_count"],
        "critic_blockers": current["hard_blockers"],
        "decision": decision, "reviewer_self_declared": reviewer, "note": note,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "approval_scope": "LOCAL_CHAINLIT_DEMO_ONLY",
        "identity_authenticated": False,
        "portal_report_registered": False, "portal_signed_review": False,
        "report_submitted_for_review": False, "publication_performed": False,
        "next_step": "MANUAL_REVISION_REQUIRED" if decision == "REQUEST_REVISION" else "NONE",
    }
    record["receipt_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
    path = _store_path(root, rid)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation is a replay/conflict barrier across multiple Chainlit sessions.
    # Does NOT claim protection against a malicious local filesystem administrator.
    try:
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError as exc:
        raise BridgeError("A human decision already exists for this reviewed version; it cannot be overwritten.") from exc
    return record



def find_existing_review(root: Path, thread_id: str) -> dict:
    """Reopen a saved live Critic review; never contacts a model or changes evidence."""
    tid = check_thread_id(thread_id)
    evidence = root / "evidence"
    items = list(evidence.glob(f"ui_stage4c3_{tid}_????????_manifest.json"))
    items = sorted((p for p in items if _ID_RE.fullmatch(p.name)),
                   key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    if len(items) > 100:
        raise BridgeError("Too many saved review manifests for this thread.")
    for item in items:
        try:
            return validate_review_bundle(root, tid, item.name.removesuffix("_manifest.json"))
        except BridgeError:
            continue
    raise BridgeError("No valid completed Stage 4C review is available for this thread.")

def receipt_markdown(record: dict) -> str:
    """Receipt accurately describes *local* user intent, never portal approval."""
    def safe(s: str) -> str:
        return str(s).replace("<", "&lt;").replace(">", "&gt;").replace("`", "'")
    safe_note = safe(record["note"])
    lines = [
        "# AnalystDesk — Local Human Report Review Receipt", "",
        f"**Decision: {record['decision']}**", "",
        f"- Local review ID: `{record['local_report_id']}`",
        f"- Research thread: `{record['thread_id']}`",
        f"- Critic phase: `{record['critic_phase']}`",
        f"- Claims supported: {record['critic_supported']}/{record['critic_claim_count']}",
        f"- Bound draft SHA-256: `{record['draft_sha256']}`",
        f"- Critic review SHA-256: `{record['critic_review_sha256']}`",
        f"- Reviewer (self-declared, not authenticated): {safe(record['reviewer_self_declared'])}",
        f"- Decision time (UTC): {record['timestamp_utc']}",
        f"- Reviewer's note: {safe_note}",
        f"- Local receipt SHA-256: `{record['receipt_sha256']}`",
        "", "**Scope:** Local Chainlit capstone demonstration only. "
        "This is not a cryptographically signed portal review, does not mutate the Stage 4C "
        "source manifest, and does not submit or publish a report.", "",
    ]
    if record["decision"] == "REQUEST_REVISION":
        lines.append("A human requested revision. No revision or model call was automatically launched.")
    if record["decision"] == "REJECT":
        lines.append("The reviewed version was rejected; it must not be treated as approved.")
    return "\n".join(lines) + "\n"

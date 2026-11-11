"""Presentation-only Stage 4C Critic review packet.

The original SHA-256-bound writer draft remains immutable. This module composes
an annotated *review packet*; it does not rewrite claims, clear blockers, approve,
submit or publish. All data is supplied by the provenance-checking review bridge.
"""
from __future__ import annotations

import re
import hashlib
from typing import Any


_VALID_PHASES = frozenset({
    "STAGE4C_READY_FOR_HUMAN_REVIEW", "STAGE4C_REVIEW_BLOCKED",
    "STAGE4C_SEMANTIC_REVIEW_PENDING", "STAGE4C_REVISION_LIMIT_REACHED",
})
_VALID_VERDICTS = frozenset({"SUPPORTED", "UNCERTAIN", "UNSUPPORTED", "NOT_REVIEWED"})


def _inline(value: Any, *, max_length: int = 1000) -> str:
    """Flatten markdown-sensitive inline data without changing its meaning."""
    s = " ".join(str(value).split())[:max_length]
    # Prevent an LLM-supplied reason from embedding Markdown table/control syntax.
    return s.replace("`", "'").replace("|", "/").replace("<", "&lt;").replace(">", "&gt;")


def build_review_packet(result: dict) -> str:
    """Construct a truthful download from a fully validated Stage 4C bridge result.

    Raises ValueError on contradictory status data instead of manufacturing a PASS.
    """
    if not isinstance(result, dict):
        raise ValueError("Missing validated review result")
    phase = result.get("phase")
    review = result.get("critic_review")
    draft = result.get("draft_markdown")
    if phase not in _VALID_PHASES or not isinstance(review, dict) or not isinstance(draft, str) or not draft.strip():
        raise ValueError("Review packet requires validated draft, review and phase")
    findings = review.get("findings")
    blockers = result.get("hard_blockers")
    if not isinstance(findings, list) or not findings or not isinstance(blockers, list):
        raise ValueError("Missing review findings or blocker list")
    if not all(isinstance(f, dict) and f.get("verdict") in _VALID_VERDICTS for f in findings):
        raise ValueError("Review contains invalid verdict")
    supported = sum(f["verdict"] == "SUPPORTED" for f in findings)
    if result.get("supported") != supported or result.get("claim_count") != len(findings):
        raise ValueError("Review counts are inconsistent")
    if result.get("human_report_approved") is not False or result.get("publication_performed") is not False:
        raise ValueError("Review packet cannot represent an approved/published report")
    if review.get("human_report_approved") is not False or review.get("publication_performed") is not False:
        raise ValueError("Critic cannot approve or publish a report")
    if blockers != review.get("hard_blockers"):
        raise ValueError("Manifest and Critic blockers differ")
    if not isinstance(result.get("draft_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", result["draft_sha256"]):
        raise ValueError("Missing immutable draft digest")
    if hashlib.sha256(draft.encode("utf-8")).hexdigest() != result["draft_sha256"]:
        raise ValueError("Original draft content failed its SHA-256 binding")
    if result.get("ready_for_human_review"):
        if phase != "STAGE4C_READY_FOR_HUMAN_REVIEW" or blockers or supported != len(findings):
            raise ValueError("Ready flag conflicts with Critic findings")
        disposition = "READY FOR HUMAN REVIEW (NOT HUMAN-APPROVED)"
    elif phase == "STAGE4C_SEMANTIC_REVIEW_PENDING":
        disposition = "AUTOMATED SEMANTIC REVIEW INCOMPLETE"
    else:
        disposition = "BLOCKED — HUMAN REVIEW REQUIRED"
    revision_count = result.get("revision_count")
    if type(revision_count) is not int or not 0 <= revision_count <= 2:
        raise ValueError("Invalid accepted revision count")
    lines = [
        "# AnalystDesk — Stage 4C Critic Review Packet",
        "",
        f"**FINAL STATUS: {disposition}**",
        "",
        f"- **Stage 4C phase:** `{phase}`",
        f"- **Critic disposition:** `{_inline(review.get('review_disposition', 'UNKNOWN'), max_length=80)}`",
        f"- **Research thread:** `{_inline(result.get('thread_id'), max_length=80)}`",
        f"- **Claims supported:** {supported} of {len(findings)} (model assessment only)",
        f"- **Accepted revisions:** {revision_count}",
        f"- **Hard blockers:** {', '.join(f'`{_inline(b, max_length=120)}`' for b in blockers) if blockers else 'None reported'}",
        "- **Human report approval:** NO",
        "- **Publication:** NOT PERFORMED",
        f"- **Original writer draft SHA-256:** `{result['draft_sha256']}`",
        "",
        "The Critic's verdicts are provisional model assessments, not human verification or a proof of entailment. "
        "An approved research plan is not an approved report.",
        "",
        "## Independent Critic findings",
        "",
    ]
    for i, finding in enumerate(findings, 1):
        claim_id = _inline(finding.get("claim_id", "unknown"), max_length=120)
        verdict = finding["verdict"]
        lines.extend([
            f"### {i}. `{claim_id}` — {verdict}",
            "",
            f"**Critic reason:** {_inline(finding.get('reason', ''), max_length=1000)}",
            "",
            "**Citations assessed:** " + (
                ", ".join(f"`{_inline(c, max_length=150)}`" for c in finding.get("citations", [])
                           if isinstance(c, str)) or "None recorded"
            ),
            "",
        ])
    lines.extend([
        "## Review and revision limitations",
        "",
        "The number of accepted revisions is not a count of attempted or rejected model edits. "
        "If zero revisions were accepted, the manifest alone does not establish why.",
        "",
        "## Appendix A — Original writer draft (unchanged, pre-Critic)",
        "",
        "The text below is the original cryptographically bound writer draft. Its embedded 'UNREVIEWED' "
        "labels and provisional notes describe the state **before** the independent Critic ran. "
        "The final review status is the one at the top of this packet. The original is preserved "
        "unaltered for auditability; failed claims have **not** been silently corrected.",
        "",
        "---",
        "",
        draft.rstrip(),
        "",
    ])
    return "\n".join(lines)

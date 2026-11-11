"""Allowlisted local bridge for offline evidence/draft viewing. No HTTP or hosted LLM.

Uses the SAME Docker API container and writable Stage 4A checkpoint as Phase 10A.
"""
from __future__ import annotations

import json

from phase10_bridge import (
    BridgeError, CONTAINER_ID_RE, DOCKER_PROJECT, DOCKER_SERVICE,
    _run_docker, check_thread_id, select_container_id,
)

MAX_PRESENTATION_BYTES = 500_000


async def fetch_offline_view(thread_id: str) -> dict:
    tid = check_thread_id(thread_id)
    lookup = [
        "docker", "ps", "--filter", f"label=com.docker.compose.project={DOCKER_PROJECT}",
        "--filter", f"label=com.docker.compose.service={DOCKER_SERVICE}",
        "--format", "{{.ID}}",
    ]
    container_id = select_container_id(await _run_docker(lookup, timeout=20))
    command = [
        "docker", "exec", "-i", container_id,
        "python", "-m", "analyst_desk.phase10_view_cli", "view",
        "--thread-id", tid,
    ]
    try:
        stdout = await _run_docker(command, timeout=900)
    except BridgeError as exc:
        raise BridgeError("Offline evidence/draft view failed inside Docker; inspect local logs.") from exc
    if not stdout or len(stdout) > MAX_PRESENTATION_BYTES:
        raise BridgeError("Offline view returned no data or exceeded the response limit.")
    try:
        obj = json.loads(stdout.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("Offline view returned invalid JSON.") from exc
    return validate_offline_view(obj, tid)


def validate_offline_view(payload: dict, thread_id: str) -> dict:
    tid = check_thread_id(thread_id)
    if not isinstance(payload, dict) or not (
        payload.get("status") == "PASS"
        and payload.get("phase") == "PHASE10_OFFLINE_EVIDENCE_AND_DRAFT_VIEW"
        and payload.get("source_thread_id") == tid
        and payload.get("approved_plan_consumed") is True
        and payload.get("llm_synthesis_performed") is False
        and payload.get("human_report_approved") is False
        and payload.get("publication_performed") is False
        and payload.get("draft_status") == "DRAFT_UNREVIEWED"
    ):
        raise BridgeError("Offline view failed its approval and non-publication contract.")
    audit = payload.get("evidence")
    if not isinstance(audit, dict) or not (
        type(audit.get("citation_count")) is int
        and 0 <= audit["citation_count"] <= 100_000
        and type(audit.get("xbrl_fact_count")) is int
        and 0 <= audit["xbrl_fact_count"] <= 100_000
        and isinstance(audit.get("risk_evidence_citations"), dict)
        and audit.get("semantic_entailment_checked") is False
    ):
        raise BridgeError("Offline evidence failed its audit contract.")
    markdown = payload.get("draft_markdown")
    if not isinstance(markdown, str) or not markdown.strip() or len(markdown) > 120_000:
        raise BridgeError("Unreviewed draft is missing or too large.")
    return payload

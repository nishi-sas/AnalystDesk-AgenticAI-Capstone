"""Phase 10B: offline, read-only presentation of Stage 4B3 evidence and Stage 4C1 draft.

Run INSIDE the local API container, against its existing approved Stage 4A checkpoint.
No persistence, hosted LLM, reviewer signature or publication is performed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

THREAD_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
MAX_DRAFT_CHARS = 120_000
MAX_RESPONSE_CHARS = 350_000


def _approved_audit(evidence: dict, thread_id: str) -> dict[str, Any]:
    """Retain only documented audited fields, never claim entailment verification."""
    if not (
        isinstance(evidence, dict)
        and evidence.get("status") == "PASS"
        and evidence.get("source_thread_id") == thread_id
        and evidence.get("approved_plan_consumed") is True
        and evidence.get("llm_synthesis_performed") is False
        and evidence.get("publication_performed") is False
        and type(evidence.get("citation_count")) is int
        and 0 <= evidence["citation_count"] <= 100_000
        and type(evidence.get("xbrl_fact_count")) is int
        and 0 <= evidence["xbrl_fact_count"] <= 100_000
        and isinstance(evidence.get("risk_evidence_citations"), dict)
    ):
        raise ValueError("AUDITED_EVIDENCE_CONTRACT_FAILED")
    return {
        "citation_count": evidence["citation_count"],
        "xbrl_fact_count": evidence["xbrl_fact_count"],
        "risk_evidence_citations": evidence["risk_evidence_citations"],
        "financial_comparability": evidence.get("financial_comparability"),
        "warnings": evidence.get("warnings", []),
        "semantic_entailment_checked": False,
        "historical_item1a_diff_performed": False,
    }


async def make_view(root: Path, thread_id: str) -> dict[str, Any]:
    """Rerun audited offline evidence, then create Stage 4C1's in-memory draft.

    This intentionally does *not* call Stage 4C1's file-writing CLI: evidence/
    is not a writable/persisted Docker mount. The same writer graph is reused.
    """
    if not isinstance(thread_id, str) or not THREAD_PATTERN.fullmatch(thread_id):
        raise ValueError("INVALID_THREAD_ID")

    # Import at execution time; tests can inject synthetic dependencies.
    from .stage4a_config import load_planner_settings
    from .stage4b_cli import approved_plan_from_stage4a
    from .stage4b3_cli import run as run_stage4b3
    from .stage4c1_writer import build_writer_graph

    # Validate persisted approval independently; never trust the UI's status.
    approved_plan = approved_plan_from_stage4a(root, thread_id)
    evidence = await run_stage4b3(root, thread_id, no_llm=True)
    audit = _approved_audit(evidence, thread_id)
    settings = load_planner_settings(root)
    writer_graph = build_writer_graph(
        allowed=settings.allowed_tickers, budget=settings.token_budget, writer=None
    )
    state = writer_graph.invoke({
        "plan": approved_plan,
        "evidence": evidence,
        "thread_id": thread_id,
    })
    if not isinstance(state, dict) or state.get("status") != "DRAFT_UNREVIEWED":
        raise ValueError("UNREVIEWED_DRAFT_CONTRACT_FAILED")
    draft = state.get("draft")
    markdown = draft.get("draft_markdown") if isinstance(draft, dict) else None
    if not isinstance(markdown, str) or not markdown.strip() or len(markdown) > MAX_DRAFT_CHARS:
        raise ValueError("OFFLINE_DRAFT_INVALID")
    response = {
        "status": "PASS",
        "phase": "PHASE10_OFFLINE_EVIDENCE_AND_DRAFT_VIEW",
        "source_thread_id": thread_id,
        "approved_plan_consumed": True,
        "llm_synthesis_performed": False,
        "human_report_approved": False,
        "publication_performed": False,
        "evidence": audit,
        "draft_status": "DRAFT_UNREVIEWED",
        "draft_markdown": markdown,
    }
    if len(json.dumps(response, ensure_ascii=False)) > MAX_RESPONSE_CHARS:
        raise ValueError("PRESENTATION_TOO_LARGE")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only offline evidence and unreviewed draft view")
    parser.add_argument("command", choices=["view"])
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--project-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        from .stage4a_config import PROJECT_ROOT
        result = asyncio.run(make_view(
            (args.project_root or PROJECT_ROOT).resolve(), args.thread_id
        ))
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return 0
    except Exception:
        # Don't leak raw SEC text, absolute paths, provider exceptions or secrets.
        print(json.dumps({"status": "ERROR", "code": "OFFLINE_PRESENTATION_FAILED"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())

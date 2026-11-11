"""Phase 10B tests: offline, no Docker, hosted model, SEC corpus or credentials."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase10_presentation import fetch_offline_view, validate_offline_view
from phase10_bridge import BridgeError
from analyst_desk.phase10_view_cli import _approved_audit, make_view

TID = "b3a5fcf8dbdb430ba814727b7c0dab14"


def view():
    return {
        "status":"PASS", "phase":"PHASE10_OFFLINE_EVIDENCE_AND_DRAFT_VIEW",
        "source_thread_id":TID, "approved_plan_consumed":True,
        "llm_synthesis_performed":False, "human_report_approved":False,
        "publication_performed":False, "draft_status":"DRAFT_UNREVIEWED",
        "draft_markdown":"# Offline unreviewed draft\n\nEvidence-based summary.",
        "evidence":{"citation_count":23, "xbrl_fact_count":6,
                    "risk_evidence_citations":{"cybersecurity":{"MSFT":["MSFT_001"]}},
                    "semantic_entailment_checked":False},
    }


def test_valid_view():
    assert validate_offline_view(view(), TID)["draft_status"] == "DRAFT_UNREVIEWED"


@pytest.mark.parametrize("path,bad", [
    ("status", "ERROR"), ("source_thread_id", "a"*32),
    ("llm_synthesis_performed", True), ("publication_performed", True),
    ("human_report_approved", True), ("approved_plan_consumed", False),
    ("draft_status", "APPROVED"), ("draft_markdown", ""),
])
def test_view_rejects_unsafe_contract(path, bad):
    data = view(); data[path] = bad
    with pytest.raises(BridgeError):
        validate_offline_view(data, TID)


def test_view_rejects_fabricated_counts_and_entailment():
    for k,v in [("citation_count", True), ("xbrl_fact_count", -1), ("semantic_entailment_checked", True)]:
        data = view(); data["evidence"][k] = v
        with pytest.raises(BridgeError):
            validate_offline_view(data, TID)


def test_approved_audit_is_just_citation_mapping():
    evidence={"status":"PASS", "source_thread_id":TID,"approved_plan_consumed":True,
        "llm_synthesis_performed":False,"publication_performed":False,
        "citation_count":2,"xbrl_fact_count":0,"risk_evidence_citations":{"cybersecurity":{"MSFT":["c1"]}},
        "warnings":["Synthetic only"]}
    assert _approved_audit(evidence,TID)["semantic_entailment_checked"] is False
    evidence["llm_synthesis_performed"] = True
    with pytest.raises(ValueError):
        _approved_audit(evidence,TID)


def test_docker_bridge_only_calls_allowlisted_container(monkeypatch):
    calls = []
    async def fake_run(args, *, timeout):
        calls.append(args)
        if args[:2] == ["docker","ps"]:
            return b"1234567890ab\n"
        assert args[:6] == ["docker","exec","-i","1234567890ab","python","-m"]
        assert "analyst_desk.phase10_view_cli" in args
        import json
        return json.dumps(view()).encode()
    monkeypatch.setattr("phase10_presentation._run_docker", fake_run)
    assert asyncio.run(fetch_offline_view(TID))["status"] == "PASS"
    assert len(calls) == 2


def test_no_arbitrary_thread_or_command(monkeypatch):
    with pytest.raises(BridgeError):
        asyncio.run(fetch_offline_view("bad"))


def test_in_memory_draft_uses_existing_approved_plan_and_no_writer(monkeypatch):
    import analyst_desk.stage4a_config as conf
    import analyst_desk.stage4b_cli as b
    import analyst_desk.stage4b3_cli as b3
    import analyst_desk.stage4c1_writer as writer
    settings=SimpleNamespace(allowed_tickers=("MSFT","GOOGL"), token_budget=80000)
    monkeypatch.setattr(conf, "load_planner_settings", lambda root: settings)
    monkeypatch.setattr(b, "approved_plan_from_stage4a", lambda root, tid: {"companies":["MSFT","GOOGL"]})
    async def fake_audit(root, tid, *, no_llm):
        assert no_llm is True
        return {"status":"PASS", "source_thread_id":TID,"approved_plan_consumed":True,
                "llm_synthesis_performed":False, "publication_performed":False,
                "citation_count":23, "xbrl_fact_count":6,"risk_evidence_citations":{}}
    monkeypatch.setattr(b3, "run", fake_audit)
    def mock_writer(*,allowed,budget,writer):
        assert writer is None
        class Graph:
            def invoke(self, request):
                assert request["thread_id"] == TID
                return {"status":"DRAFT_UNREVIEWED", "draft":{"draft_markdown":"# offline draft"}}
        return Graph()
    monkeypatch.setattr(writer, "build_writer_graph", mock_writer)
    result=asyncio.run(make_view(Path("."),TID))
    assert result["draft_markdown"] == "# offline draft"
    assert result["publication_performed"] is False
    assert result["human_report_approved"] is False

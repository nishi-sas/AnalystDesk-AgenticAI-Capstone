"""Stage 4B-1: approved-plan, source-grounded parallel research via read-only MCP.

No generative interpretation, code execution, draft storage or publication here.
Actual MCP dispatch goes through FastMCP client; test doubles use the same contract.
"""
from __future__ import annotations

import operator
import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Awaitable, Callable, Protocol, TypedDict

from .stage4a_graph import validate_plan, PlanningError
from .stage4a_permissions import assert_tool_permission


class ResearchError(RuntimeError):
    pass


class ToolCaller(Protocol):
    async def __call__(self, role: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ResearchState(TypedDict, total=False):
    plan: dict[str, Any]
    approved: bool
    ticker: str
    research_results: Annotated[list[dict[str, Any]], operator.add]
    status: str
    summary: dict[str, Any]


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_SEC_URL = "https://www.sec.gov/Archives/"


def check_approved_plan(plan: Any, *, approved: bool, allowed: tuple[str, ...], budget: int) -> dict[str, Any]:
    """Reject unapproved, malformed or scope-escalating plans before any MCP call."""
    if approved is not True:
        raise ResearchError("Cannot dispatch research without an approved plan")
    if not isinstance(plan, dict):
        raise ResearchError("Missing approved plan")
    try:
        validated = validate_plan(plan, candidates=list(allowed), max_budget=budget)
    except PlanningError as exc:
        raise ResearchError("Approved plan failed validation: " + str(exc)) from None
    return validated


def _tool_data(response: Any, name: str) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("ok") is not True or not isinstance(response.get("data"), dict):
        code = response.get("error_code") if isinstance(response, dict) else None
        raise ResearchError(f"{name} did not return verified tool data ({code or 'BAD_RESPONSE'})")
    return response["data"]


def _hits(data: dict, ticker: str, item: str, *, report_date: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    hits = data.get("hits")
    if not isinstance(hits, list):
        raise ResearchError("Search response missing hits array")
    output = []
    seen = set()
    for hit in hits[:10]:
        if not isinstance(hit, dict) or hit.get("ticker") != ticker or hit.get("item") != item:
            raise ResearchError("Search returned source outside requested company/item")
        if report_date is not None and hit.get("report_date") != report_date:
            raise ResearchError("Search evidence period differs from requested SEC filing")
        digest = hit.get("source_sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ResearchError("Search evidence is missing a valid source checksum")
        pid = hit.get("passage_id")
        url = hit.get("source_url")
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_.\-]{8,160}", pid):
            raise ResearchError("Invalid canonical passage ID")
        if not isinstance(url, str) or not url.startswith(_SEC_URL):
            raise ResearchError("Evidence not backed by SEC Archives URL")
        if pid not in seen:
            seen.add(pid)
            output.append({"passage_id": pid, "ticker": ticker, "item": item,
                           "report_date": hit.get("report_date"), "source_url": url,
                           "source_sha256": hit.get("source_sha256"),
                           "snippet": str(hit.get("snippet", ""))[:360],
                           "untrusted_source_text": True})
        if len(output) >= limit:
            break
    return output


def _filings(data: dict, ticker: str) -> list[dict[str, Any]]:
    entries = data.get("filings")
    if not isinstance(entries, list) or not entries:
        raise ResearchError("EDGAR returned no annual filing periods")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("ticker") != ticker:
            raise ResearchError("EDGAR returned a wrong-company filing")
        if not isinstance(entry.get("report_date"), str) or not _ISO_DATE.fullmatch(entry["report_date"]):
            raise ResearchError("EDGAR filing has invalid fiscal date")
        if not isinstance(entry.get("filing_url"), str) or not entry["filing_url"].startswith(_SEC_URL):
            raise ResearchError("EDGAR filing URL is not an SEC Archives URL")
    return sorted(entries, key=lambda v: v["report_date"], reverse=True)


def _metric(data: dict, ticker: str, expected_date: str, expected_operation: str) -> dict:
    if data.get("name") != expected_operation or data.get("ticker") != ticker:
        raise ResearchError("Calculation returned wrong company or metric")
    field = "report_date" if expected_operation == "operating_margin" else "current_report_date"
    if data.get(field) != expected_date:
        raise ResearchError("Calculation returned a mismatched fiscal period")
    value = data.get("value_percent")
    if not isinstance(value, str):
        raise ResearchError("Calculation missing exact percentage string")
    try:
        if not Decimal(value).is_finite():
            raise ResearchError("Calculation returned a nonfinite percentage")
    except InvalidOperation:
        raise ResearchError("Calculation returned a nonnumeric percentage") from None
    operands = data.get("operands")
    if not isinstance(operands, list) or not operands or not all(isinstance(v, str) and "|us-gaap:" in v for v in operands):
        raise ResearchError("Calculation missing XBRL operand fact IDs")
    if data.get("source_verified_by") != "EDGAR_SHA256_URL_SIDECARS":
        raise ResearchError("Calculation lacks verified SEC source provenance")
    return {"value_percent": value, "operands": list(operands),
            "report_date": expected_date, "source_verified_by": data["source_verified_by"]}


async def research_company(ticker: str, plan: dict, call: ToolCaller) -> dict[str, Any]:
    """One company branch: risk/MD&A evidence + reported filings + verified ratios.

    Retrieval/calc failures are explicit warnings, never invented fallback values.
    Source validation errors are fatal because they would invalidate auditability.
    """
    if ticker not in plan["companies"]:
        raise ResearchError("Dispatch ticker absent from approved plan")

    async def permitted(role: str, name: str, arguments: dict[str, Any]) -> dict:
        assert_tool_permission(role, name)
        return await call(role, name, arguments)

    listing = _filings(_tool_data(await permitted("quant", "list_annual_filings", {"ticker": ticker, "years": 3}), "list_annual_filings"), ticker)
    latest = listing[0]["report_date"]
    prior = listing[1]["report_date"] if len(listing) > 1 else None
    findings: dict[str, Any] = {
        "ticker": ticker, "report_date": latest, "filings": [
            {"report_date": f["report_date"], "accession": f["accession"], "filing_url": f["filing_url"]} for f in listing],
        "evidence": {"risk": [], "mda": []}, "metrics": {}, "warnings": [],
        "historical_item1a_comparison_performed": False,
    }
    for key, item, query in (
        ("risk", "1A", "material cybersecurity competition regulatory legal risk factors"),
        ("mda", "7", "revenue operating performance growth cloud advertising segments"),
    ):
        role = "risk_diff" if key == "risk" else "filing_researcher"
        data = _tool_data(await permitted(role, "search_passages", {
            "query": query, "ticker": ticker, "item": item, "report_date": latest,
            "top_n": 3, "rerank": True}), "search_passages")
        findings["evidence"][key] = _hits(data, ticker, item, report_date=latest)
        if not findings["evidence"][key]:
            findings["warnings"].append(f"NO_{item}_PASSAGES_FOR_{latest}")

    margin_result = await permitted("quant", "calculate_operating_margin", {"ticker": ticker, "report_date": latest})
    if margin_result.get("ok") is True:
        findings["metrics"]["operating_margin"] = _metric(_tool_data(margin_result, "calculate_operating_margin"), ticker, latest, "operating_margin")
    else:
        findings["warnings"].append("OPERATING_MARGIN_UNAVAILABLE:" + str(margin_result.get("error_code", "UNKNOWN")))
    if prior:
        growth_result = await permitted("quant", "calculate_revenue_growth", {
            "ticker": ticker, "current_report_date": latest, "prior_report_date": prior})
        if growth_result.get("ok") is True:
            findings["metrics"]["revenue_growth_yoy"] = _metric(_tool_data(growth_result, "calculate_revenue_growth"), ticker, latest, "revenue_growth_yoy")
            findings["metrics"]["revenue_growth_yoy"]["prior_report_date"] = prior
        else:
            findings["warnings"].append("REVENUE_GROWTH_UNAVAILABLE:" + str(growth_result.get("error_code", "UNKNOWN")))
    else:
        findings["warnings"].append("PRIOR_YEAR_FILING_UNAVAILABLE")
    findings["warnings"].append("HISTORICAL_ITEM1A_COMPARISON_NOT_AVAILABLE_UNTIL_PRIOR_10K_CORPUS_INGESTED")
    return findings


def build_research_graph(*, call: ToolCaller, allowed: tuple[str, ...], budget: int):
    """True LangGraph Send fan-out; collecting nodes use an additive state reducer."""
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Send

    def gate(state: ResearchState) -> dict:
        validated = check_approved_plan(state.get("plan"), approved=state.get("approved", False), allowed=allowed, budget=budget)
        return {"plan": validated, "status": "RESEARCH_DISPATCHED"}

    def dispatch(state: ResearchState):
        return [Send("company_research", {"ticker": tick, "plan": state["plan"]}) for tick in state["plan"]["companies"]]

    async def branch(state: ResearchState) -> dict:
        output = await research_company(state["ticker"], state["plan"], call)
        return {"research_results": [output]}

    def consolidate(state: ResearchState) -> dict:
        results = sorted(state.get("research_results", []), key=lambda v: state["plan"]["companies"].index(v["ticker"]))
        if len(results) != len(state["plan"]["companies"]) or {v["ticker"] for v in results} != set(state["plan"]["companies"]):
            raise ResearchError("Parallel fan-out did not return one result per company")
        warnings = [{"ticker": r["ticker"], "code": code} for r in results for code in r["warnings"]]
        citations = sorted({h["passage_id"] for r in results for group in r["evidence"].values() for h in group})
        facts = sorted({fact for r in results for m in r["metrics"].values() for fact in m["operands"]})
        return {"status": "RESEARCH_EVIDENCE_READY", "summary": {
            "companies": [r["ticker"] for r in results], "citations": citations,
            "xbrl_fact_ids": facts, "warnings": warnings, "publication_performed": False,
            "analytical_draft_generated": False, "LLM_synthesis_performed": False}}

    builder = StateGraph(ResearchState)
    builder.add_node("approved_plan_gate", gate)
    builder.add_node("company_research", branch)
    builder.add_node("consolidate", consolidate)
    builder.add_edge(START, "approved_plan_gate")
    builder.add_conditional_edges("approved_plan_gate", dispatch, ["company_research"])
    builder.add_edge("company_research", "consolidate")
    builder.add_edge("consolidate", END)
    return builder.compile()

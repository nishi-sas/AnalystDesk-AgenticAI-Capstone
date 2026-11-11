"""AnalystDesk local Chainlit interface: planning, approval, audited SEC research.

The FastAPI backend remains the source of truth for permissions and research.
Displaying or downloading a draft is NOT report approval or publication.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import chainlit as cl
import httpx

from phase10_presentation import fetch_offline_view
from phase10_review_bridge import run_live_review
from phase10_ui_helpers import (
    FOCUS_OPTIONS, SUPPORTED_TICKERS, compose_research_request,
    extract_financial_rows, financial_table, workflow_mermaid,
)

from phase10_bridge import (
    API_URL, BridgeError, check_thread_id, decode_sse_block, stage4a,
    validate_completed,
)


def buttons(thread_id: str, status: str) -> list[cl.Action]:
    if status == "PENDING_PLAN_REVIEW":
        return [
            cl.Action(name="approve_plan", payload={"thread_id": thread_id},
                      label="Approve plan", icon="check-circle"),
            cl.Action(name="reject_plan", payload={"thread_id": thread_id},
                      label="Reject plan", icon="x-circle"),
        ]
    if status == "PLAN_APPROVED":
        return [cl.Action(name="run_research", payload={"thread_id": thread_id},
                          label="Run approved research (offline)", icon="play")]
    return []


async def show_plan(result: dict) -> None:
    tid = check_thread_id(result["thread_id"])
    status = result.get("status", "UNKNOWN")
    plan = result.get("plan")
    pending = result.get("pending_interrupt") is True
    if status == "PENDING_PLAN_REVIEW" and not pending:
        raise BridgeError("Plan lacks a pending human-review interrupt.")
    cl.user_session.set("thread_id", tid)
    cl.user_session.set("status", status)
    text = (
        f"**Stage 4A status:** `{status}`\n\n"
        f"**Thread ID:** `{tid}`\n\n"
        f"**Planner:** deterministic offline demonstration (no LLM calls)\n\n"
        f"**Human review pending:** `{pending}`\n\n"
        f"**Proposed plan:**\n```json\n{json.dumps(plan, indent=2, ensure_ascii=False)}\n```"
    )
    # Clear *all* actions in the previous plan message, including the sibling
    # Approve/Reject button. A stale callback is still rejected server-side.
    previous = cl.user_session.get("plan_action_message")
    if previous is not None:
        await previous.remove_actions()
        previous.actions = []
    current = cl.Message(content=text, actions=buttons(tid, status))
    await current.send()
    cl.user_session.set("plan_action_message", current if current.actions else None)


async def error_message(exc: Exception) -> None:
    # Do not echo raw provider/HTTP errors, local paths or secret-bearing metadata.
    message = str(exc) if isinstance(exc, BridgeError) else "Unexpected local error; inspect the terminal."
    await cl.Message(content=f"**Operation stopped:** {message}").send()


@cl.on_chat_start
async def on_start() -> None:
    cl.user_session.set("thread_id", None)
    cl.user_session.set("status", None)
    cl.user_session.set("plan_action_message", None)
    cl.user_session.set("last_audited_research", None)
    cl.user_session.set("reviewed_thread_id", None)
    cl.user_session.set("review_in_progress", False)
    cl.user_session.set("company_a", "MSFT")
    cl.user_session.set("company_b", "GOOGL")
    cl.user_session.set("analysis_focus", FOCUS_OPTIONS[0])
    await cl.ChatSettings([
        cl.input_widget.Select(
            id="company_a", label="First company", values=list(SUPPORTED_TICKERS),
            initial_index=SUPPORTED_TICKERS.index("MSFT"),
        ),
        cl.input_widget.Select(
            id="company_b", label="Second company", values=list(SUPPORTED_TICKERS),
            initial_index=SUPPORTED_TICKERS.index("GOOGL"),
        ),
        cl.input_widget.Select(
            id="analysis_focus", label="Analysis focus", values=list(FOCUS_OPTIONS),
            initial_index=0,
        ),
    ]).send()
    api_note = (
        "The expanded local release is selected in this UI process. "
        if os.getenv("ANALYSTDESK_VERIFIED_RELEASE_ID") else
        "The UI lists the 12 verified tickers; the research API may still be using "
        "its original company scope. Configure the API separately before researching other companies. "
    )
    await cl.Message(content=(
        "# AnalystDesk | SEC Research Workbench\n\n"
        "Select two companies in **Chat Settings**, then write a research question in your own words. "
        "The planner will pause for your approval before research executes.\n\n"
        "**Try:** Compare operating margin, sales growth, cybersecurity disclosures, "
        "and management commentary from available annual filings.\n\n"
        + api_note + "\n\n"
        "**Commands:** `/status` | `/attach <32-character-thread-id>` | `/workflow`. "
        "Research runs offline. Live Writer/Critic review is separately available by explicit action "
        "after research and uses OpenRouter model credits. No report is automatically human-approved or published."
    )).send()


@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    """Settings affect the next request only, never an already approved plan."""
    a = settings.get("company_a", cl.user_session.get("company_a"))
    b = settings.get("company_b", cl.user_session.get("company_b"))
    focus = settings.get("analysis_focus", cl.user_session.get("analysis_focus"))
    if a not in SUPPORTED_TICKERS or b not in SUPPORTED_TICKERS or focus not in FOCUS_OPTIONS:
        await cl.Message(content="Invalid company settings; previous selections retained.").send()
        return
    cl.user_session.set("company_a", a)
    cl.user_session.set("company_b", b)
    cl.user_session.set("analysis_focus", focus)
    if a == b:
        await cl.Message(content="Choose two **different** companies before starting research.").send()
    else:
        await cl.Message(content=(
            f"Next request: **{a} versus {b}** — {focus}. "
            "Changes do not alter an existing approval checkpoint."
        )).send()


async def show_workflow() -> None:
    diagram = workflow_mermaid()
    await cl.Message(
        content=(
            "## AnalystDesk workflow (architecture overview)\n\n"
            "```mermaid\n" + diagram + "```\n\n"
            "The Chainlit **Steps** panel shows actual local execution steps. "
            "The diagram is an architectural overview, not a recorded trace."
        ),
        elements=[cl.File(
            name="analystdesk_workflow.mmd", content=diagram.encode("utf-8"),
            mime="text/plain", display="side",
        )],
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    content = message.content.strip()
    if not content:
        return
    try:
        if content.lower() == "/workflow":
            await show_workflow()
            return
        if content.lower() == "/status":
            tid = cl.user_session.get("thread_id")
            if not tid:
                raise BridgeError("No plan attached. Enter a research request or /attach <thread-id>.")
            await show_plan(await stage4a("status", tid))
            return
        if content.startswith("/attach "):
            tid = check_thread_id(content[len("/attach "):].strip())
            cl.user_session.set("last_audited_research", None)
            await show_plan(await stage4a("status", tid))
            return
        if content.startswith("/"):
            raise BridgeError("Unknown command. Use /status, /attach <thread-id>, or /workflow.")
        if cl.user_session.get("status") == "PENDING_PLAN_REVIEW":
            raise BridgeError("Approve or reject your pending plan before starting another request.")
        cl.user_session.set("last_audited_research", None)
        cl.user_session.set("reviewed_thread_id", None)
        company_a = cl.user_session.get("company_a")
        company_b = cl.user_session.get("company_b")
        focus = cl.user_session.get("analysis_focus")
        try:
            research_request = compose_research_request(content, company_a, company_b, focus)
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        tid = uuid.uuid4().hex
        async with cl.Step(name="Stage 4A — Create offline plan", type="tool") as step:
            step.input = f"Research thread {tid}; requested {company_a} versus {company_b}"
            result = await stage4a("start", tid, request=research_request)
            if result.get("status") != "PENDING_PLAN_REVIEW" or result.get("pending_interrupt") is not True:
                raise BridgeError("Planning did not reach the required human-review interrupt.")
            planned = result.get("plan") or {}
            if set(planned.get("companies", [])) != {company_a, company_b}:
                raise BridgeError("Planner company scope differs from the selected pair; approval refused.")
            step.output = "Stopped at the persisted human-review interrupt"
        await show_plan(result)
    except Exception as exc:
        await error_message(exc)


async def handle_decision(action: cl.Action, decision: str) -> None:
    try:
        tid = check_thread_id(action.payload.get("thread_id"))
        if tid != cl.user_session.get("thread_id"):
            raise BridgeError("Review action is not bound to the active session thread.")
        state = await stage4a("status", tid)
        if state.get("status") != "PENDING_PLAN_REVIEW" or state.get("pending_interrupt") is not True:
            raise BridgeError("This plan is no longer pending review.")
        result = await stage4a("resume", tid, decision=decision)
        if decision == "APPROVE" and result.get("status") != "PLAN_APPROVED":
            raise BridgeError("The plan was not approved; research remains blocked.")
        if decision == "REJECT" and result.get("status") != "PLAN_REJECTED":
            raise BridgeError("The rejection outcome could not be verified.")
        # show_plan removes every action on the prior review message.
        await show_plan(result)
    except Exception as exc:
        await error_message(exc)


@cl.action_callback("approve_plan")
async def approve_plan(action: cl.Action) -> None:
    await handle_decision(action, "APPROVE")


@cl.action_callback("reject_plan")
async def reject_plan(action: cl.Action) -> None:
    await handle_decision(action, "REJECT")


@cl.action_callback("run_research")
async def run_research(action: cl.Action) -> None:
    """Consume the existing FastAPI SSE endpoint; do not forge success events."""
    try:
        tid = check_thread_id(action.payload.get("thread_id"))
        if tid != cl.user_session.get("thread_id"):
            raise BridgeError("Research action is not bound to the active session thread.")
        state = await stage4a("status", tid)
        if state.get("status") != "PLAN_APPROVED" or state.get("plan_approved") is not True:
            raise BridgeError("A persisted approved plan is required before research.")
        completed = None
        seen_started = False
        async with cl.Step(name="Stage 4B3 — Audited offline research", type="tool") as step:
            step.input = f"Approved thread: {tid}"
            step.output = "Connecting to local research API"
            async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10), trust_env=False) as client:
                async with client.stream("POST", API_URL, json={"thread_id": tid}) as response:
                    if response.status_code != 200:
                        raise BridgeError(f"Research API refused request (HTTP {response.status_code}).")
                    lines = []
                    async for line in response.aiter_lines():
                        if line != "":
                            lines.append(line)
                            if len(lines) > 25:
                                raise BridgeError("Research stream frame exceeded its limits.")
                            continue
                        if not lines:
                            continue
                        event, payload = decode_sse_block("\n".join(lines))
                        lines.clear()
                        if event == "started":
                            if payload.get("status") != "RUNNING" or payload.get("thread_id") != tid or payload.get("llm_enabled") is not False:
                                raise BridgeError("Research start contract failed.")
                            seen_started = True
                            step.output = "Running approved Stage 4B3 evidence retrieval (no LLM)"
                            await step.update()
                        elif event == "error":
                            raise BridgeError("Research API reported an error or busy worker; inspect Docker logs.")
                        elif event == "completed":
                            if not seen_started:
                                raise BridgeError("Completion received without a valid start event.")
                            completed = validate_completed(payload)
                    if lines:
                        raise BridgeError("Research stream ended with an incomplete frame.")
            if completed is None:
                raise BridgeError("Research stream ended without a successful completed event.")
            step.output = "PASS — Existing approved plan consumed; no synthesis or publication"
        cl.user_session.set("last_audited_research", {
            "thread_id": tid,
            "citation_count": completed["citation_count"],
            "xbrl_fact_count": completed["xbrl_fact_count"],
        })
        await cl.Message(content=(
            f"## Research execution: PASS\n\n"
            f"**Approved thread:** `{tid}`\n\n"
            f"**SEC citation references:** {completed['citation_count']}\n\n"
            f"**XBRL facts:** {completed['xbrl_fact_count']}\n\n"
            "**Hosted LLM synthesis:** disabled\n\n"
            "**Publication:** not performed\n\n"
            "The counts describe retrieved evidence, **not independently verified claim correctness**. "
            "Open **View evidence and draft** to inspect analysis and download Markdown. "
            "The offline draft is unreviewed. Use the explicit Writer/Critic action to create a separate reviewed draft.\n\n"
            "Monitoring: [Grafana](http://127.0.0.1:3000) · "
            "[Prometheus](http://127.0.0.1:9090)"
        ), actions=[
            cl.Action(name="view_offline_draft", payload={"thread_id": tid},
                      label="View evidence and draft", icon="file-text"),
            cl.Action(name="run_stage4c_review", payload={"thread_id": tid},
                      label="Run Writer/Critic review (OpenRouter credits)", icon="shield-check"),
        ]).send()
    except Exception as exc:
        await error_message(exc)


@cl.action_callback("view_offline_draft")
async def view_offline_draft(action: cl.Action) -> None:
    """Explicit, read-only offline presentation; never signs/publishes."""
    try:
        tid = check_thread_id(action.payload.get("thread_id"))
        audited = cl.user_session.get("last_audited_research")
        if not isinstance(audited, dict) or audited.get("thread_id") != tid:
            raise BridgeError("Run approved research in this chat before viewing its offline draft.")
        if tid != cl.user_session.get("thread_id"):
            raise BridgeError("Presentation action is not bound to the active session thread.")
        checkpoint = await stage4a("status", tid)
        if checkpoint.get("status") != "PLAN_APPROVED" or checkpoint.get("plan_approved") is not True:
            raise BridgeError("A persisted approved plan is required before viewing evidence.")
        async with cl.Step(name="Stage 4C1 — Offline evidence and unreviewed draft", type="tool") as step:
            step.input = f"Approved thread: {tid}; no hosted LLM or publication"
            step.output = "Rechecking SEC evidence and constructing the offline draft"
            result = await fetch_offline_view(tid)
            audit = result["evidence"]
            if (audit["citation_count"] != audited["citation_count"] or
                    audit["xbrl_fact_count"] != audited["xbrl_fact_count"]):
                raise BridgeError("Rerun evidence counts differ from the prior audit; inspect sources.")
            step.output = "PASS — citation mapping and unreviewed draft; no publishing"

        citations = json.dumps(audit["risk_evidence_citations"], indent=2, ensure_ascii=False)
        facts = json.dumps(audit.get("financial_comparability"), indent=2, ensure_ascii=False)
        warnings = json.dumps(audit.get("warnings", []), indent=2, ensure_ascii=False)
        markdown = result["draft_markdown"]
        company_scope = tuple((checkpoint.get("plan") or {}).get("companies", []))
        rows = extract_financial_rows(markdown, company_scope)
        elements = [
            cl.Text(name="Risk evidence passage IDs", content=citations, display="side"),
            cl.Text(name="Financial comparability", content=facts, display="side"),
            cl.Text(name="Retrieval warnings", content=warnings, display="side"),
            cl.Text(name="Unreviewed offline draft", content=markdown, display="side"),
            cl.File(name=f"AnalystDesk_{tid[:10]}_UNREVIEWED.md",
                    content=markdown.encode("utf-8"), mime="text/markdown", display="side"),
        ]
        if rows:
            # Optional chart: the table and Markdown download always work even if
            # the UI environment does not have Plotly installed.
            try:
                import plotly.graph_objects as go
                chart = go.Figure()
                chart.add_bar(name="Operating margin", x=[r.ticker for r in rows],
                              y=[r.operating_margin for r in rows])
                chart.add_bar(name="Revenue growth YoY", x=[r.ticker for r in rows],
                              y=[r.revenue_growth_yoy for r in rows])
                chart.update_layout(title="SEC XBRL-backed financial comparison (draft)",
                                    barmode="group", yaxis_title="Percent", height=420)
                elements.append(cl.Plotly(name="Financial comparison chart",
                                          figure=chart, display="inline"))
            except (ImportError, AttributeError):
                pass
        await cl.Message(
            content=(
                "## SEC evidence and downloadable offline draft\n\n"
                f"**Approved thread:** `{tid}`\n\n"
                f"**SEC citation references:** {audit['citation_count']} | "
                f"**XBRL facts:** {audit['xbrl_fact_count']}\n\n"
                "### Financial comparisons (from the generated draft)\n\n"
                + financial_table(rows) + "\n\n"
                "Use the attached Markdown file to **download the draft**. "
                "Risk passages, financial provenance and warnings are available as attachments.\n\n"
                "**Status: UNREVIEWED AND NOT APPROVED.** This is the offline presentation path, "
                "not the independent live Writer/Critic or portal-approved report. "
                "Retrieved citations alone do not establish semantic entailment."
            ),
            elements=elements,
            actions=[cl.Action(
                name="run_stage4c_review", payload={"thread_id": tid},
                label="Run Writer/Critic review (OpenRouter credits)", icon="shield-check",
            )],
        ).send()
    except Exception as exc:
        await error_message(exc)


@cl.action_callback("run_stage4c_review")
async def run_stage4c_review(action: cl.Action) -> None:
    """Explicit opt-in paid review; fail closed on stale/non-approved research."""
    try:
        tid = check_thread_id(action.payload.get("thread_id"))
        audited = cl.user_session.get("last_audited_research")
        if tid != cl.user_session.get("thread_id") or not isinstance(audited, dict) or audited.get("thread_id") != tid:
            raise BridgeError("First complete approved research for the active thread.")
        if cl.user_session.get("reviewed_thread_id") == tid:
            raise BridgeError("This thread already has a reviewed draft in this session. See the prior review message.")
        if cl.user_session.get("review_in_progress") is True:
            raise BridgeError("A Writer/Critic review is already in progress.")
        checkpoint = await stage4a("status", tid)
        if checkpoint.get("status") != "PLAN_APPROVED" or checkpoint.get("plan_approved") is not True:
            raise BridgeError("The Stage 4A checkpoint is not approved; review refused.")
        cl.user_session.set("review_in_progress", True)
        try:
            async with cl.Step(name="Stage 4C3 — Live Writer / Critic / bounded revision", type="tool") as step:
                step.input = f"Approved research thread {tid}. Explicit OpenRouter calls; human report approval disabled."
                step.output = "Running isolated review using the verified SEC release and Docker checkpoint"
                result = await run_live_review(tid)
                step.output = (f"{result['phase']}; {result['supported']}/{result['claim_count']} "
                               "claims supported; no human approval or publication")
            cl.user_session.set("reviewed_thread_id", tid)
        finally:
            cl.user_session.set("review_in_progress", False)
        status = ("CRITIC REVIEWED — READY FOR HUMAN REVIEW"
                  if result["ready_for_human_review"] else "CRITIC REVIEWED — BLOCKED OR INCOMPLETE")
        blockers = result["hard_blockers"]
        company_scope = tuple((checkpoint.get("plan") or {}).get("companies", []))
        reviewed_rows = extract_financial_rows(result["draft_markdown"], company_scope)
        elements = [
            cl.File(name=f"AnalystDesk_{tid[:10]}_CRITIC_REVIEWED_UNAPPROVED.md",
                    content=result["draft_markdown"].encode("utf-8"),
                    mime="text/markdown", display="side"),
            cl.Text(name="Critic findings and verdicts",
                    content=json.dumps(result["critic_review"], indent=2, ensure_ascii=False),
                    display="side"),
        ]
        await cl.Message(content=(
            "## Stage 4C Writer–Critic report\n\n"
            f"**Status:** {status}\n\n"
            f"**Thread:** `{tid}`\n\n"
            f"**Review phase:** `{result['phase']}`\n\n"
            f"**Critic claims supported:** {result['supported']}/{result['claim_count']}\n\n"
            f"**Bounded revisions:** {result['revision_count']}\n\n"
            f"**Hard blockers:** {json.dumps(blockers, ensure_ascii=False)}\n\n"
            "### Financial comparison from the reviewed draft\n\n"
            + financial_table(reviewed_rows) + "\n\n"
            f"**Draft SHA-256:** `{result['draft_sha256']}`\n\n"
            "The attached Markdown is **reviewed by the model Critic**, not approved by a human. "
            "Critic support is provisional, not proof of semantic entailment. "
            "**No approval, portal submission or publication was performed.** "
            "Use the Critic findings attachment to inspect individual claim verdicts."
        ), elements=elements).send()
    except Exception as exc:
        await error_message(exc)


@cl.action_callback("show_workflow")
async def show_workflow_action(action: cl.Action) -> None:
    await show_workflow()

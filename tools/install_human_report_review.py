"""Conservative additive installer for the second Chainlit human-review gate.

Works with either Phase 10 Writer/Critic UI or review-packet-export UI. All existing
code paths are preserved; only bounded anchor insertions/replacements are made.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import textwrap

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "chainlit_app.py"
MODULE = ROOT / "phase10_human_review.py"
EXPORT = ROOT / "phase10_review_export.py"
PATCH_DIR = ROOT / "ui_patch"
IMPORT_ANCHOR = "from phase10_review_bridge import run_live_review\n"
START_ANCHOR = '    cl.user_session.set("reviewed_thread_id", None)\n    cl.user_session.set("review_in_progress", False)\n'
ATTACH_ANCHOR = '            cl.user_session.set("last_audited_research", None)\n            await show_plan(await stage4a("status", tid))\n'
NEW_ANCHOR = '        cl.user_session.set("reviewed_thread_id", None)\n        company_a ='
STAGE4C_RESULT_ANCHOR = '            cl.user_session.set("reviewed_thread_id", tid)\n        finally:'
ELEMENT_ANCHOR_OLD = '''            cl.File(name=f"AnalystDesk_{tid[:10]}_CRITIC_REVIEWED_UNAPPROVED.md",
                    content=result["draft_markdown"].encode("utf-8"),
                    mime="text/markdown", display="side"),'''
ELEMENT_REPLACEMENT = '''            cl.File(name=f"AnalystDesk_{tid[:10]}_REVIEW_PACKET_UNAPPROVED.md",
                    content=build_review_packet(result).encode("utf-8"),
                    mime="text/markdown", display="side"),'''
DESC_ANCHOR_OLD = 'The attached Markdown is **reviewed by the model Critic**, not approved by a human. '
DESC_REPLACEMENT = ('The attached review packet contains the Critic verdicts and the original unmodified writer draft. '
                    'It is **not approved by a human**. ')
END_REVIEW_ANCHOR = '''            "Use the Critic findings attachment to inspect individual claim verdicts."
        ), elements=elements).send()'''
END_REVIEW_NEW = '''            "Use the Critic findings attachment to inspect individual claim verdicts.\\n\\n"
            "**Human report gate:** a local reviewer can approve only a Critic-cleared report, "
            "or request revision/reject any reviewed report. Decision receipts are retained locally "
            "without portal submission or publication."
        ), elements=elements, actions=review_actions)'''
END_INSERT_ANCHOR = '\n\n@cl.action_callback("show_workflow")\n'

HANDLERS = r'''

async def _begin_human_review(action: cl.Action, decision: str) -> None:
    """Button selects intention only; a separate typed confirmation is required."""
    try:
        result = cl.user_session.get("review_result")
        tid = check_thread_id(action.payload.get("thread_id"))
        if tid != cl.user_session.get("thread_id") or not isinstance(result, dict) or result.get("thread_id") != tid:
            raise BridgeError("Report decision is not bound to this active research thread.")
        if action.payload.get("local_report_id") != local_report_id(result):
            raise BridgeError("Report decision refers to a different reviewed version.")
        if cl.user_session.get("review_in_progress"):
            raise BridgeError("Writer/Critic is still running.")
        if decision == "APPROVE" and not can_approve(result):
            raise BridgeError("Approval is disabled while the Critic reports blockers or uncertain claims.")
        if read_decision(ROOT, result) is not None:
            raise BridgeError("A decision has already been recorded for this reviewed version.")
        checkpoint = await stage4a("status", tid)
        if checkpoint.get("status") != "PLAN_APPROVED" or checkpoint.get("plan_approved") is not True:
            raise BridgeError("The original research-plan approval cannot be verified.")
        cl.user_session.set("pending_human_decision", {
            "decision": decision, "thread_id": tid, "local_report_id": local_report_id(result)
        })
        await cl.Message(content=(
            "## Confirm local human report decision\n\n"
            f"**Decision:** `{decision}` | **Local report ID:** `{local_report_id(result)}`\n\n"
            f"Reply exactly in this format:\n\n`{decision} | Your Name | Your review note`\n\n"
            "Use your own reviewer name and a brief explanation. Type `/cancel` to abort. "
            "This records a local, self-declared review decision only: it does not digitally sign, "
            "submit or publish a portal report."
        )).send()
    except Exception as exc:
        await error_message(exc)


@cl.action_callback("approve_human_report")
async def approve_human_report(action: cl.Action) -> None:
    await _begin_human_review(action, "APPROVE")


@cl.action_callback("revise_human_report")
async def revise_human_report(action: cl.Action) -> None:
    await _begin_human_review(action, "REQUEST_REVISION")


@cl.action_callback("reject_human_report")
async def reject_human_report(action: cl.Action) -> None:
    await _begin_human_review(action, "REJECT")
'''

REPLY_HANDLER = r'''        pending = cl.user_session.get("pending_human_decision")
        if pending is not None:
            if content.lower() == "/cancel":
                cl.user_session.set("pending_human_decision", None)
                await cl.Message(content="Human report decision cancelled. No decision recorded.").send()
                return
            reviewer, note = parse_confirmation(content, pending["decision"])
            result = cl.user_session.get("review_result")
            if not isinstance(result, dict) or result.get("thread_id") != pending["thread_id"] or local_report_id(result) != pending["local_report_id"] or pending["thread_id"] != cl.user_session.get("thread_id"):
                raise BridgeError("The pending human-review confirmation is stale; no decision recorded.")
            checkpoint = await stage4a("status", pending["thread_id"])
            if checkpoint.get("status") != "PLAN_APPROVED" or checkpoint.get("plan_approved") is not True:
                raise BridgeError("Research plan approval is no longer valid; no decision recorded.")
            receipt = record_decision(ROOT, result, pending["decision"], reviewer, note)
            cl.user_session.set("pending_human_decision", None)
            review_message = cl.user_session.get("human_review_action_message")
            if review_message is not None:
                try:
                    await review_message.remove_actions()
                except Exception:
                    # The immutable receipt is already saved. Stale callbacks
                    # are independently rejected via read_decision().
                    pass
            cl.user_session.set("human_review_action_message", None)
            receipt_text = receipt_markdown(receipt)
            await cl.Message(content=(
                "## Local human report decision recorded\n\n"
                f"**Decision:** `{receipt['decision']}`\n\n"
                f"**Local report ID:** `{receipt['local_report_id']}`\n\n"
                f"**Reviewer (self-declared):** {receipt['reviewer_self_declared']}\n\n"
                f"**Bound draft SHA-256:** `{receipt['draft_sha256']}`\n\n"
                "A decision receipt is attached. **No portal signature, submission, publication "
                "or automated revision has occurred.**"
            ), elements=[cl.File(name=f"AnalystDesk_{receipt['local_report_id']}_HUMAN_DECISION.md",
                                 content=receipt_text.encode("utf-8"),
                                 mime="text/markdown", display="side")]).send()
            return
        if content.startswith(("APPROVE |", "REJECT |", "REQUEST_REVISION |")):
            raise BridgeError("Choose a human-review action from its report message before confirming.")
'''


def unique_replace(text: str, before: str, after: str, label: str) -> str:
    if text.count(before) != 1:
        raise ValueError(f"Chainlit UI mismatch at {label}: expected one anchor, got {text.count(before)}")
    return text.replace(before, after, 1)


def transform(text: str) -> str:
    if "from phase10_human_review import" in text:
        if "@cl.action_callback(\"approve_human_report\")" not in text:
            raise ValueError("Partial human approval gate detected; refusing overwrite")
        return text
    if "from phase10_review_export import build_review_packet" not in text:
        text = unique_replace(text, IMPORT_ANCHOR,
            IMPORT_ANCHOR + "from phase10_review_export import build_review_packet\n", "review packet import")
        text = unique_replace(text, ELEMENT_ANCHOR_OLD, ELEMENT_REPLACEMENT, "review packet attachment")
        text = unique_replace(text, DESC_ANCHOR_OLD, DESC_REPLACEMENT, "review packet description")
    text = unique_replace(text, 'from phase10_review_export import build_review_packet\n',
        'from phase10_review_export import build_review_packet\n'
        'from phase10_human_review import (can_approve, find_existing_review, local_report_id, parse_confirmation,\n'
        '    read_decision, receipt_markdown, record_decision)\n'
        'from phase10_bridge import ROOT\n', "human gate imports")
    text = unique_replace(text, START_ANCHOR,
        START_ANCHOR + '    cl.user_session.set("review_result", None)\n'
        '    cl.user_session.set("pending_human_decision", None)\n'
        '    cl.user_session.set("human_review_action_message", None)\n', "start session keys")
    text = unique_replace(text, ATTACH_ANCHOR,
        '            cl.user_session.set("review_result", None)\n'
        '            cl.user_session.set("pending_human_decision", None)\n'
        '            cl.user_session.set("human_review_action_message", None)\n'
        + ATTACH_ANCHOR, "attach state cleanup")
    text = unique_replace(text, NEW_ANCHOR,
        '        cl.user_session.set("review_result", None)\n'
        '        cl.user_session.set("pending_human_decision", None)\n'
        '        cl.user_session.set("human_review_action_message", None)\n'
        + NEW_ANCHOR, "new research cleanup")
    text = unique_replace(text, '    try:\n        if content.lower() == "/workflow":',
        '    try:\n' + REPLY_HANDLER + '        if content.lower() == "/workflow":', "human confirmation")
    text = unique_replace(text, '        if content.startswith("/attach "):',
        '''        if content.startswith("/review "):
            tid = check_thread_id(content[len("/review "):].strip())
            checkpoint = await stage4a("status", tid)
            if checkpoint.get("status") != "PLAN_APPROVED" or checkpoint.get("plan_approved") is not True:
                raise BridgeError("A persisted approved research plan is required for human report review.")
            result = find_existing_review(ROOT, tid)
            cl.user_session.set("thread_id", tid)
            cl.user_session.set("status", "PLAN_APPROVED")
            cl.user_session.set("reviewed_thread_id", tid)
            cl.user_session.set("review_result", result)
            cl.user_session.set("pending_human_decision", None)
            await present_human_review(tid, checkpoint, result)
            return
        if content.startswith("/attach "):''', "review resume command")
    text = unique_replace(text, STAGE4C_RESULT_ANCHOR,
        STAGE4C_RESULT_ANCHOR.replace('        finally:', '            cl.user_session.set("review_result", result)\n        finally:'), "persist reviewed result in session")
    text = unique_replace(text, '        await cl.Message(content=(\n            "## Stage 4C Writer–Critic report',
        '''        rid = local_report_id(result)
        prior = read_decision(ROOT, result)
        review_actions = []
        if prior is None:
            if can_approve(result):
                review_actions.append(cl.Action(name="approve_human_report",
                    payload={"thread_id": tid, "local_report_id": rid},
                    label="Approve report locally", icon="check-circle"))
            review_actions.extend([
                cl.Action(name="revise_human_report",
                    payload={"thread_id": tid, "local_report_id": rid},
                    label="Request revision", icon="refresh-cw"),
                cl.Action(name="reject_human_report",
                    payload={"thread_id": tid, "local_report_id": rid},
                    label="Reject report", icon="x-circle"),
            ])
        report_message = cl.Message(content=(
            "## Stage 4C Writer–Critic report''', "human review action creation")
    text = unique_replace(text, END_REVIEW_ANCHOR,
        END_REVIEW_NEW + '\n        await report_message.send()\n'
        '        cl.user_session.set("human_review_action_message", report_message if review_actions else None)',
        "human review action attachment")
    text = unique_replace(text, END_INSERT_ANCHOR, HANDLERS + END_INSERT_ANCHOR, "human decision handlers")
    # Single reusable rendering path for newly generated and previously saved reviews.
    start_marker = '        status = ("CRITIC REVIEWED — READY FOR HUMAN REVIEW"'
    end_marker = '        cl.user_session.set("human_review_action_message", report_message if review_actions else None)'
    left = text.index(start_marker)
    right = text.index(end_marker, left) + len(end_marker)
    original_section = text[left:right]
    function = 'async def present_human_review(tid, checkpoint, result):\n' + textwrap.indent(textwrap.dedent(original_section), '    ') + '\n\n'
    text = text[:left] + '        await present_human_review(tid, checkpoint, result)' + text[right:]
    position = text.index('\n@cl.action_callback("run_stage4c_review")')
    text = text[:position] + '\n' + function + text[position:]
    text = text.replace('`/status` | `/attach <32-character-thread-id>` | `/workflow`',
                        '`/status` | `/attach <thread-id>` | `/review <thread-id>` | `/workflow`')
    text = text.replace('Use /status, /attach <thread-id>, or /workflow.',
                        'Use /status, /attach <thread-id>, /review <thread-id>, or /workflow.')
    text = text.replace('Explicit OpenRouter calls; human report approval disabled.',
                        'Explicit OpenRouter calls; no automatic human report approval.')
    compile(text, "chainlit_app.py", "exec")
    return text


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit("No chainlit_app.py in the AnalystDesk root")
    src = PATCH_DIR / "phase10_human_review.py"
    exporter = PATCH_DIR / "phase10_review_export.py"
    if not src.is_file() or not exporter.is_file():
        raise SystemExit("Extract the complete patch ZIP into project root")
    old_ui = TARGET.read_text(encoding="utf-8")
    try:
        new_ui = transform(old_ui)
        compile(src.read_text(encoding="utf-8"), src.name, "exec")
    except (ValueError, SyntaxError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
    old_module = MODULE.read_bytes() if MODULE.is_file() else None
    old_export = EXPORT.read_bytes() if EXPORT.is_file() else None
    if old_module is not None and old_module != src.read_bytes():
        raise SystemExit("Existing phase10_human_review.py differs; refusing overwrite")
    if old_export is not None and old_export != exporter.read_bytes():
        raise SystemExit("Existing review exporter differs; refusing overwrite")
    if new_ui == old_ui and old_module == src.read_bytes() and old_export == exporter.read_bytes():
        print("ALREADY_INSTALLED: no changes required")
        return
    backup = ROOT / "backups" / ("human_review_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    backup.mkdir(parents=True)
    shutil.copy2(TARGET, backup / "chainlit_app.py")
    if old_module is not None:
        (backup / MODULE.name).write_bytes(old_module)
    if old_export is not None:
        (backup / EXPORT.name).write_bytes(old_export)
    try:
        MODULE.write_bytes(src.read_bytes())
        if old_export is None:
            EXPORT.write_bytes(exporter.read_bytes())
        TARGET.write_text(new_ui, encoding="utf-8")
    except Exception:
        TARGET.write_text(old_ui, encoding="utf-8")
        if old_module is None:
            MODULE.unlink(missing_ok=True)
        else:
            MODULE.write_bytes(old_module)
        if old_export is None:
            EXPORT.unlink(missing_ok=True)
        else:
            EXPORT.write_bytes(old_export)
        raise
    print("PATCHED: added local human report review with durable decision receipts")
    print("BACKUP:", backup)
    print("Only Chainlit Windows files changed; no Docker rebuild or paid calls")


if __name__ == "__main__":
    main()

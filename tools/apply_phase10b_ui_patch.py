"""Guarded additive patch to the locally validated Phase 10 Chainlit app.

Only adds a new offline evidence/draft action; preserves Stage 4A gate, SSE,
previous Phase 10 scope/UI fixes. Makes one ignored .bak backup.
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'chainlit_app.py'

IMPORT_ANCHOR = 'from phase10_bridge import (\n'
IMPORT_NEW = 'from phase10_presentation import fetch_offline_view\n\n' + IMPORT_ANCHOR

SESSION_ANCHOR = '    cl.user_session.set("plan_action_message", None)\n'
SESSION_NEW = SESSION_ANCHOR + '    cl.user_session.set("last_audited_research", None)\n'

NEW_REQUEST_ANCHOR = '        tid = uuid.uuid4().hex\n        async with cl.Step(name="Stage 4A — Create offline plan", type="tool") as step:\n'
NEW_REQUEST_NEW = '        cl.user_session.set("last_audited_research", None)\n' + NEW_REQUEST_ANCHOR

ATTACH_ANCHOR = '            tid = check_thread_id(content[len("/attach "):].strip())\n            await show_plan(await stage4a("status", tid))\n'
ATTACH_NEW = '            tid = check_thread_id(content[len("/attach "):].strip())\n            cl.user_session.set("last_audited_research", None)\n            await show_plan(await stage4a("status", tid))\n'

RESULT_ANCHOR = (
    '        await cl.Message(content=(\n'
    '            f"## Research execution: PASS\\n\\n"\n'
)
RESULT_NEW = (
    '        cl.user_session.set("last_audited_research", {\n'
    '            "thread_id": tid,\n'
    '            "citation_count": completed["citation_count"],\n'
    '            "xbrl_fact_count": completed["xbrl_fact_count"],\n'
    '        })\n'
    + RESULT_ANCHOR
)

BUTTON_ANCHOR = (
    '            "[Prometheus](http://127.0.0.1:9090)"\n'
    '        )).send()\n'
)
BUTTON_NEW = (
    '            "[Prometheus](http://127.0.0.1:9090)"\n'
    '        ), actions=[cl.Action(\n'
    '            name="view_offline_draft", payload={"thread_id": tid},\n'
    '            label="View evidence + offline draft", icon="file-text",\n'
    '        )]).send()\n'
)

APPEND = '''\n\n@cl.action_callback("view_offline_draft")
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
        await cl.Message(
            content=(
                "## SEC evidence and unreviewed draft\\n\\n"
                f"**Approved thread:** `{tid}`\\n\\n"
                f"**SEC citation references:** {audit['citation_count']}\\n\\n"
                f"**XBRL facts:** {audit['xbrl_fact_count']}\\n\\n"
                "**Risk evidence passage IDs** and **Unreviewed offline draft** are attached. "
                "Financial comparability and retrieval warnings are also available.\\n\\n"
                "The draft is **not human-reviewed, verified or approved for publication**. "
                "Passage identifiers and counts are not semantic entailment checks. "
                "Neither an LLM nor a publication operation was invoked."
            ),
            elements=[
                cl.Text(name="Risk evidence passage IDs", content=citations, display="side"),
                cl.Text(name="Financial comparability", content=facts, display="side"),
                cl.Text(name="Retrieval warnings", content=warnings, display="side"),
                cl.Text(name="Unreviewed offline draft", content=result["draft_markdown"], display="side"),
            ],
        ).send()
    except Exception as exc:
        await error_message(exc)
'''


def one(text: str, old: str, new: str, description: str) -> str:
    amount = text.count(old)
    if amount != 1:
        raise RuntimeError(f'{description}: expected 1 anchor, found {amount}; no files changed')
    return text.replace(old, new, 1)


def main() -> None:
    original = UI.read_text(encoding='utf-8')
    if 'view_offline_draft' in original:
        raise RuntimeError('Phase 10B UI patch already applied; no files changed')
    if 'await previous.remove_actions()' not in original:
        raise RuntimeError('Phase 10 scope/UI safety patch missing; no files changed')
    updated = original
    for old, new, label in (
        (IMPORT_ANCHOR, IMPORT_NEW, 'bridge import'),
        (SESSION_ANCHOR, SESSION_NEW, 'session reset'),
        (ATTACH_ANCHOR, ATTACH_NEW, 'attach'),
        (NEW_REQUEST_ANCHOR, NEW_REQUEST_NEW, 'new request'),
        (RESULT_ANCHOR, RESULT_NEW, 'audited result'),
        (BUTTON_ANCHOR, BUTTON_NEW, 'presentation action'),
    ):
        updated = one(updated, old, new, label)
    updated += APPEND
    ast.parse(updated, filename=str(UI))
    backup = UI.with_name('chainlit_app.py.phase10b_pre_view.bak')
    if backup.exists():
        raise RuntimeError('Backup already exists; refusing to overwrite it')
    shutil.copy2(UI, backup)
    UI.write_text(updated, encoding='utf-8')
    print('Phase 10B UI patch applied; original backed up as chainlit_app.py.phase10b_pre_view.bak')
    print('No source agents, approval checkpoints or monitoring configuration changed')


if __name__ == '__main__':
    main()

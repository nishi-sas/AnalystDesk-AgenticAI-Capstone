"""Apply narrowly guarded Phase 10 fixes to an existing AnalystDesk checkout.

No plan is approved, changed or resumed. No LLM call, network access or Docker
operation is performed. Makes local, ignored backup copies before modifying files.
Run at project root: python tools/apply_phase10_scope_ui_fix.py
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "src" / "analyst_desk" / "stage4a_graph.py"
UI = ROOT / "chainlit_app.py"

ORIGINAL_PLANNER_ANCHOR = (
    '    """Explicit demo-only path: avoids network/LLM and must never be presented as agent-generated."""\n'
)
PLANNER_MARKER = "# Phase 10: deterministic request-aware risk-only demo branch"
PLANNER_BRANCH = '''    # Phase 10: deterministic request-aware risk-only demo branch.
    # Preserve the preexisting general-purpose demo template for all other requests.
    # This is simple lexical routing, not natural-language understanding or an LLM.
    intent = request.casefold()
    wants_risk = re.search(r"\\b(?:risk|risks|cybersecurity|competition|litigation)\\b", intent) is not None
    wants_numbers = re.search(
        r"\\b(?:revenue|income|margin|profit|earnings|sales)\\b|cash flow", intent
    ) is not None
    if wants_risk and not wants_numbers:
        questions = [
            f"Identify principal risk factors disclosed by {ticker} in SEC Form 10-K Item 1A, with source IDs."
            for ticker in tickers
        ]
        if len(tickers) > 1:
            questions.append(
                "Compare the disclosed risk factors across the requested companies, "
                "preserving each filing's reporting period and source provenance."
            )
        return {
            "companies": tickers,
            "sub_questions": questions[:8],
            "outline": ["Scope and reporting periods", "Principal risk factors", "Comparative risks and limitations"],
            "token_budget": budget,
        }
'''

UI_ORIGINAL = '    await cl.Message(content=text, actions=buttons(tid, status)).send()\n'
UI_REPLACEMENT = '''    # Clear *all* actions in the previous plan message, including the sibling
    # Approve/Reject button. A stale callback is still rejected server-side.
    previous = cl.user_session.get("plan_action_message")
    if previous is not None:
        await previous.remove_actions()
        previous.actions = []
    current = cl.Message(content=text, actions=buttons(tid, status))
    await current.send()
    cl.user_session.set("plan_action_message", current if current.actions else None)
'''
UI_START_ORIGINAL = '    cl.user_session.set("thread_id", None)\n    cl.user_session.set("status", None)\n'
UI_START_NEW = UI_START_ORIGINAL + '    cl.user_session.set("plan_action_message", None)\n'
UI_ACTION_ORIGINAL = '        await action.remove()\n        await show_plan(result)\n'
UI_ACTION_NEW = '        # show_plan removes every action on the prior review message.\n        await show_plan(result)\n'


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor, found {count}; no files changed")
    return text.replace(old, new, 1)


def main() -> None:
    original_planner = PLANNER.read_text(encoding="utf-8")
    original_ui = UI.read_text(encoding="utf-8")
    if PLANNER_MARKER in original_planner or 'plan_action_message' in original_ui:
        raise RuntimeError("Patch appears already applied; no files changed")
    if not ("import re" in original_planner or "import re," in original_planner):
        raise RuntimeError("Planner's re import could not be confirmed; no files changed")
    planner = replace_exact(original_planner, ORIGINAL_PLANNER_ANCHOR,
                            ORIGINAL_PLANNER_ANCHOR + PLANNER_BRANCH, "planner")
    ui = replace_exact(original_ui, UI_ORIGINAL, UI_REPLACEMENT, "UI message")
    ui = replace_exact(ui, UI_START_ORIGINAL, UI_START_NEW, "UI session")
    ui = replace_exact(ui, UI_ACTION_ORIGINAL, UI_ACTION_NEW, "UI callback")
    # Syntax-check *both* edits before touching the working source.
    ast.parse(planner, filename=str(PLANNER))
    ast.parse(ui, filename=str(UI))
    planner_backup = PLANNER.with_name(PLANNER.name + ".phase10_original.bak")
    ui_backup = UI.with_name(UI.name + ".phase10_original.bak")
    if planner_backup.exists() or ui_backup.exists():
        raise RuntimeError("Backup exists; refusing to overwrite it")
    shutil.copy2(PLANNER, planner_backup)
    shutil.copy2(UI, ui_backup)
    PLANNER.write_text(planner, encoding="utf-8")
    UI.write_text(ui, encoding="utf-8")
    print("Phase 10 scope/UI patch applied: 2 files updated, originals preserved as *.bak")
    print("No checkpoint, Docker container, approval, or research execution was modified")


if __name__ == "__main__":
    main()

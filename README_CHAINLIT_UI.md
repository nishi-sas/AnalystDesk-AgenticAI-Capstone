# AnalystDesk Chainlit workbench upgrade

## Installation

Extract the archive into your AnalystDesk project root. It should create:

- `ui_patch/chainlit_app.py` (staged replacement; does **not** overwrite your working file)
- `ui_patch/phase10_ui_helpers.py`
- `tools/apply_chainlit_workbench_ui.py`
- `tests/test_phase10_ui_helpers.py`

Run, in the project `(Analystdesk)` environment:

```bat
python tools\apply_chainlit_workbench_ui.py
python -m pytest -q tests\test_phase10_ui_helpers.py
```

Then stop/restart the existing Chainlit UI (in its own environment) as usual:

```bat
conda activate analystdesk-ui
python -m chainlit run chainlit_app.py --host 127.0.0.1 --port 8001
```

## Features

- Dropdowns in Chainlit Chat Settings for the two companies and analysis focus.
- Free-text question composed with the selected company scope, with a strict mismatch check before presenting plan approval.
- Existing LangGraph human approval and FastAPI SSE research path untouched.
- Downloadable Markdown **unreviewed** draft; evidence, provenance and limitations shown.
- Financial table and optional Plotly chart, using only rows present in the generated draft. Plotly is optional.
- `/workflow` overview with a downloadable Mermaid `.mmd` diagram; actual executed steps appear in Chainlit's Steps panel.

## Important limits

- **Do not claim** that Chat Settings configure Docker. The backend must independently use the expanded 12-company corpus and allowlist before selecting TGT/HD; the existing Docker API may still be MSFT/GOOGL-only.
- This patch deliberately does **not** create a live Writer/Critic/portal endpoint, approve reports, or publish anything. The UI currently displays/downloads the existing **offline** draft only.
- A Mermaid architectural diagram is **not** a captured dynamic LangGraph execution trace.
- Existing `phase10_bridge.py` and `phase10_presentation.py` remain unchanged.
- Installer refuses installation if the local `chainlit_app.py` differs from the exact 273-line source supplied for inspection, to protect working changes.

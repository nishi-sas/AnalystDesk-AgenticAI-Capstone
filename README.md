# AnalystDesk Stage 4C — safe CLI error visibility patch

Scope: **only** `phase10_review_bridge.py` on Windows. The Docker API, SEC corpus, verified 12-company release, existing research and Chainlit app remain unchanged.

## Install

1. Stop Chainlit (`Ctrl+C`); keep Docker running.
2. Extract this ZIP into the AnalystDesk project root, preserving `ui_patch/`, `tools/`, and `tests/` directories.
3. In `(Analystdesk)` CMD at project root:

```bat
python tools\apply_stage4c_diagnostic_patch.py
python -m pytest -q tests\test_phase10_review_bridge_diagnostics.py
```

4. Restart Chainlit in `analystdesk-ui` as usual.

The patch checks the SHA-256 of the original Stage 4C integration and refuses to overwrite any unexpected version. It backs up the old file under `backups/`. If refused, **do not force replacement**; send the refusal output.

## What changes

`stage4c3_cli.py` deliberately returns bounded JSON with `status=ERROR`, `error_type` and a sanitized `message` when it exits unsuccessfully. Previously the Windows bridge discarded that stdout, producing the generic error in Chainlit. The new bridge only parses this structured error; never includes raw Docker stderr or unstructured stdout; redacts key/token-like strings.

No OpenRouter calls happen during installation or unit testing. The next click on **Run Writer/Critic review** is a real model call and may incur charges. Make it only once. If it fails, report the `error_type` and safe message displayed in Chainlit; never share `.env` or an API key.

An offline `STAGE4C_SEMANTIC_REVIEW_PENDING` pass is expected and is **not** a live semantic review.

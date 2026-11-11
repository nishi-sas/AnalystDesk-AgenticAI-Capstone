# AnalystDesk Stage 4C — company-specific summaries and safe Rewriter diagnostics

## Why
Two live Chainlit comparisons (TGT vs HD; ADBE vs LOW) produced verified SEC/XBRL evidence and 4 of 5 Critic-supported claims. The `executive_summary` claim was `UNCERTAIN` because it overstated links between disclosures. Zero accepted revisions is consistent with an output-validation rejection in the Rewriter. The prior manifest did not explain that rejection.

## What changes
- `src/analyst_desk/stage4c1_writer.py`: asks the Writer to attribute each company's risks separately and avoid unsupported causal claims. **No changes** to citation validation, numeric integrity, data or approval logic.
- `src/analyst_desk/stage4c3_revision.py`: strengthens Rewriter attribution instructions; preserves fail-closed behaviour; adds a fixed-enumeration diagnostic code (`revision_failure`) if the Rewriter exhausts its schema retries. The safe diagnostic names the rejected claim IDs without exposing provider output or source excerpts. Failed revisions remain unaccepted.
- `src/analyst_desk/stage4c3_cli.py`: includes the optional `revision_failure` field in the saved manifest so the rejection reason is inspectable.

**This patch does not guarantee five supported claims. The Critic remains independent; no human approval or publication occurs automatically.**

## Installation (Windows CMD, Analystdesk environment)
1. Keep your existing working project and datasets. Extract this ZIP into your AnalystDesk project root. It adds `tools/` and `tests/` files only.
2. Execute:
   ```bat
   python tools\apply_stage4c_summary_diagnostics.py
   python -m pytest -q tests\test_stage4c_summary_diagnostics_patch.py
   ```
   The installer checks source anchors and Python syntax **before changing anything**, backs up each changed source file under `backups/stage4c_summary_diag_.../`, and can be run again safely.
3. Rebuild **only** the Docker API image (because backend `src/` changed):
   ```bat
   docker compose up -d --build --no-deps analystdesk-api
   docker compose exec -T analystdesk-api python -c "from analyst_desk.stage4c3_revision import _safe_rewriter_failure_code; print('NEW_STAGE4C_CODE_OK')"
   curl.exe http://127.0.0.1:8000/healthz
   ```
4. Restart Chainlit; no UI patch needed:
   ```bat
   conda activate analystdesk-ui
   python -m chainlit run chainlit_app.py --host 127.0.0.1 --port 8001
   ```
5. Run **one** explicitly authorized live Writer/Critic comparison using the previously approved ADBE/LOW thread `0ce1f488a9f640819bcc69914d6e5c09` or an approved fresh research thread. In Chainlit, `/attach <thread-id>`, run approved research, then click Writer/Critic once (this incurs OpenRouter charges). Do not click twice or retry until you have seen the result.
6. Check the new `evidence/ui_stage4c3_*_manifest.json` file for:
   - `phase` (`STAGE4C_READY_FOR_HUMAN_REVIEW` if Critic-cleared, otherwise blocked/limit)
   - `versions` and `revision_count`
   - `revision_failure` (null if no schema failure, or safe code and claim IDs)
   - `hard_blockers`, `human_report_approved=false`, `publication_performed=false`
7. If the report is cleared, demonstrate the **local** human approval action; if blocked, request revision or reject. Never bypass a blocker.

## Scope and caveats
- This does **not** solve missing SEC cache coverage for other companies. Preflight the entire verified cohort separately before final submission.
- Do not add OpenRouter API keys or `.env` to the submission ZIP.
- This diagnostic only covers `RewriterOutputRetriesExhausted`; other exceptions intentionally continue to fail closed and propagate.
- Full repository regression, live model calls, and end-to-end acceptance on the user's Windows/Docker environment have **not** been executed here.
- If the source anchors do not match your installed version, the installer aborts without modifying files. Do not force the edit; share the failure output.

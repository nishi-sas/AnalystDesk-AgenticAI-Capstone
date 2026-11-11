# Phase 6 closure — Windows installation

This archive contains two Markdown documents only; it does not change Python source, SEC cache, portal database or tests.

1. Extract the ZIP into the AnalystDesk **project root**, preserving `security/`.
2. This updates only `security/PHASE6D_FINAL_ACCEPTANCE_ADDENDUM.md`, replacing the *draft* addendum distributed with the 6D-3/6D-4 patch. It does **not** overwrite `security/threat_model.md`.
3. Check `EXECUTION_LOG.md` has no existing `PHASE 6 TECHNICAL VALIDATION COMPLETE` entry; if absent, append the provided `PHASE6_COMPLETION_ENTRY_20261027.md` once:

   ```bat
   findstr /I /C:"PHASE 6 TECHNICAL VALIDATION COMPLETE" EXECUTION_LOG.md
   type PHASE6_COMPLETION_ENTRY_20261027.md >> EXECUTION_LOG.md
   ```

4. Optional verification:

   ```bat
   if exist security\PHASE6D_FINAL_ACCEPTANCE_ADDENDUM.md (echo SECURITY ADDENDUM FOUND) else (echo MISSING)
   findstr /I /C:"PASS_WITH_RESIDUAL_RISKS" security\PHASE6D_FINAL_ACCEPTANCE_ADDENDUM.md
   ```

Do not repeat full regression just to install two Markdown files. Final submission must still undergo ZIP secret scanning, and risk sign-off/deployment authorization remain pending.

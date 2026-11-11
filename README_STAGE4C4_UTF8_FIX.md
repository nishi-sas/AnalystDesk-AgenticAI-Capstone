# AnalystDesk Stage 4C-4 Windows UTF-8 test correction

Corrects a cross-platform test fixture only. Replaces `tests/test_stage4c4_portal.py` with the same tests except `test_missing_fiscal_numeric_provenance_refused` now explicitly reads and writes the altered Markdown as UTF-8, keeping the SHA-256 calculation bound to the same decoded bytes. No application source or security contract changes.

1. Extract the ZIP into your AnalystDesk project root, **replacing** `tests/test_stage4c4_portal.py` only.
2. Run `python -m pytest -q tests/test_stage4c4_portal.py > evidence\60a_stage4c4_utf8_targeted.txt 2>&1`.
3. Run `python -m pytest -v > evidence\60b_stage4c4_tests_retry.txt 2>&1` and inspect the summary. Expected: 346 passing tests.
4. If both pass, proceed with `stage4c4_cli register` using the previously validated manifest. Register **once**, since it creates a persistent portal draft.

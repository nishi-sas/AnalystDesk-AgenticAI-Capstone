# AnalystDesk: provenance-sidecar staging correction

## Root cause

The selector copied only each `.htm`/HTML file into its isolated workspace. The existing strict `document_parsing.process_manifest()` also requires the sibling `*.htm.meta.json` provenance sidecar produced by the SEC downloader. Because the initial 36 filenames were copied without sidecars, all six original technology companies failed with `Provenance sidecar missing`. The downloaded replacement companies passed because the isolated downloader created their sidecars there.

**The existing company filings did not fail parsing in that run.** Their extraction was not reached. Oracle 2025 remains a separately established unsupported Item 8 cross-reference layout. Other candidates may fail for legitimate reasons.

## Contents and effects

- `tools/apply_verified_coverage_sidecar_fix.py`: idempotent, AST-validated patch. Modifies `tools/build_verified_coverage.py` and updates one synthetic downloader fixture in `tests/test_verified_coverage_selector.py` to provide the metadata sidecar that the real downloader already writes. Both files are backed up.
- `tests/test_verified_coverage_sidecar_fix.py`: offline checks for staging source HTML/sidecars, re-stage conflicts, missing original provenance, candidate-sidecar publication, missing-sidecar refusal, sidecar mismatch and symlink refusal.

The fix carries original SEC sidecars **alongside** HTML into staging; it never fabricates a missing sidecar. For successful replacement companies it also preserves their sidecars when copying newly approved documents into the ordinary SEC cache. Existing source parsing security checks are unchanged. No primary corpus, index, checkpoint, Chainlit, or Docker edits.

## Windows CMD instructions from project root

1. Extract ZIP contents, merging `tools` and `tests` folders (do not overwrite entire folders).
2. Run:

```bat
python tools\apply_verified_coverage_sidecar_fix.py
python -m pytest -q tests\test_verified_coverage_selector.py tests\test_verified_coverage_cwd_fix.py tests\test_verified_coverage_sidecar_fix.py
python -m pytest -q
python tools\build_verified_coverage.py
```

Prior baseline **930 passed, 4 skipped**. Seven new regression tests should bring it to **937 passed, 4 skipped** when symlink creation is available. On Windows, the symlink test may skip, giving **936 passed, 5 skipped**. All original tests should still pass because the test-only fake downloader now writes realistic metadata sidecars.

The first two attempted coverage runs were not published. They may be retained as diagnostics. This new run should start `PASS` for legitimately supported originals and `EXCLUDED` only for genuine extraction/provenance failures. A full pass still requires **6 technology and 6 commerce/retail companies, 3 filings each**; partial results do not publish `current.json`.

## Do not claim a fully verified dataset yet

`PARSER_VALIDATED` means per-filing structural and SEC provenance checks succeeded, **not** that numerical accuracy or every section boundary was independently reviewed. The expanded index and UI are not switched automatically.

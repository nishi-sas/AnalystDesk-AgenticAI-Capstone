# AnalystDesk — Isolated SEC Cache Path Fix

## Root cause

The coverage selector previously ran the existing filing parser from the **original repository working directory**, while passing a cache root inside its **isolated staging workspace**. The original parser resolves SEC manifest `local_path` values relative to the process working directory, so every valid SEC filing appeared to escape the isolated cache. This is why all 15 companies failed with the same `Manifest path escapes SEC cache` error.

It was **not** evidence that 15 companies have unsupported Form 10-K structures.

## Correction

The new selector uses the isolated staging workspace as its current directory only during the strict `process_manifest()` call. It restores the previous directory in a `finally` block, including if parsing fails. **The parser itself and its path-traversal protection are unchanged.** The candidate remains rejected if actual extraction or verification fails. Oracle 2025 should therefore fail as an unsupported *Item 8 layout*, not a cache path error.

## Install (Windows CMD, active Analystdesk environment)

1. Extract this ZIP into `D:\IIT-B_Agentic_Ai\Capstone\AnalystDesk`, merging directories.
2. Apply the narrowly scoped patch and verify it is idempotent:

```bat
python tools\apply_verified_coverage_cwd_fix.py
python -m pytest -q tests\test_verified_coverage_selector.py tests\test_verified_coverage_cwd_fix.py
python -m pytest -q
```

3. Re-run only the selector:

```bat
python tools\build_verified_coverage.py
```

The failed `_work/20261101T081517Z_fb9bf4d7` workspace is an audit artifact; it does not need to be deleted. Previously downloaded replacement HTML is in that isolated workspace. A new run will download replacements again unless a future optimization introduces a checksum-validated staging-cache reuse mechanism. **Do not delete the existing 36 SEC documents.**

## Expected changes

The run should report `PASS` for properly parsed companies and `EXCLUDED: ORCL 2025-05-31 failed extraction: ... Item 8` for the known unsupported Oracle fiscal 2025 filing. Additional company-specific parsing failures are possible and will be handled by new same-sector candidates. `data/verified_coverage/current.json` is only updated when the full selected-company quota is satisfied.

The previous baseline was 920 passed, 4 skipped before the eight selector tests, or 928 passed, 4 skipped once installed. This package adds two tests, so if everything was already installed and no other changes occurred, expect **930 passed, 4 skipped**.

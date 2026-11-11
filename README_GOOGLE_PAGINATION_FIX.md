# AnalystDesk — GOOGL Item 8 pagination fragments (selector-only fix)

## Diagnosis

Three Google filings (2025, 2024, 2023) parsed successfully, 979 raw passages. Existing selector rejected 26 short passages; 20 visible samples were standalone SEC printed page numbers, such as `44.`, `46.` and `87.`. SEC source files were valid UTF-8 and contained no literal U+FFFD bytes. **The six unprinted samples must be checked by the supplied preflight**; do not assume they are pagination until confirmed.

## Scope

This patch changes **only** `tools/build_verified_coverage.py`. It adds a narrow `standalone_item8_page_number()` predicate for *non-table* Item 8 text matching exactly 1–3 digits and a period (`44.`). These fragments are excluded from the **new expanded corpus only**. Their original passage IDs and page labels are recorded in each per-filing summary and the selection audit. Original IDs of retained passages are not altered. The original parser remains strict.

Unrelated short passages, replacement characters, numerical cells inside tables, and incorrectly structured sections still trigger rejection. The already published expanded version and original Microsoft–Google corpus/index are not changed until a subsequent successful selection run updates the version pointer atomically. No active Docker/Chainlit configuration changes.

## Install (Windows CMD, from repository root)

Extract ZIP preserving directories, then:

```
python tools\apply_verified_coverage_pagination_fix.py
python -m pytest -q tests\test_verified_coverage_pagination_fix.py tests\test_verified_coverage_selector.py tests\test_verified_coverage_cwd_fix.py tests\test_verified_coverage_sidecar_fix.py
python -m pytest -q
```

The new test module adds **8** offline tests; previous full regression was `930 passed, 4 skipped`, so expected full is `938 passed, 4 skipped` if nothing else has changed.

## Preflight Google (read-only)

```
python tools\check_google_pagination.py
```

Expected based on diagnostic: 3 filings, 979 source passages, 26 previously rejected short passages, 26 standalone page labels, **0 other invalid passages**. If the last count is nonzero, do not bypass validation: inspect the remaining fragments.

## Build replacement corpus

```
python tools\build_verified_coverage.py
```

Google should now be accepted if all 26 invalid passages satisfy the precise page-label rule. The code handles similar clearly identified printed pagination in other companies but never removes real short text or tables. The selector will still fail closed on any unexpected format, and will publish the new release only if complete two-sector / three-year coverage succeeds.

A successful Google inclusion would replace a **later technology backup** (expected AMD) in the 6-company tech set. `data/verified_coverage/current.json` changes only on success. The original primary corpus and index remain unchanged.

## Verify

Use the printed `SUCCESS` and `PASS` lines, and inspect the new release's `selection_audit.json` and `10k_verified_parse_summary.json`. Each Google filing summary retains:

- `original_passage_count`
- `passage_count` (non-pagination passages in expanded corpus)
- `excluded_pagination_fragment_ids`
- `excluded_pagination_fragment_texts`

The audit includes an `excluded_pagination_fragments` count and per-year `pagination_exclusion_audit`, preserving traceability. This is structural/provenance validation; it does not certify all numbers or paragraph semantics.

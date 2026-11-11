# AnalystDesk Stage 2B — Fail-Closed, Replacement-Aware SEC Coverage

**Purpose:** select 12 parser-compatible companies (6 technology + 6 commerce/retail), with **three distinct annual 10-K filings per company**. If **any** annual filing of a company fails extraction or structural/provenance checks, exclude that *entire company* and automatically try a **previously unused ticker in the same sector**.

This is a **sidecar workflow**, not a modification to `document_parsing.py`, `filings_cli.py`, `sec_client.py`, the original MSFT/GOOGL corpus, embeddings/index, test evidence, checkpoints, Docker, or Chainlit. It uses the *existing* strict parser and SEC downloader.

## Files in this ZIP

- `tools/build_verified_coverage.py` — standalone coverage orchestrator
- `tests/test_verified_coverage_selector.py` — 8 offline regression tests
- `docs/PRESENTATION_SCOPE_NOTE.md` — wording for presentation, demonstration and limitations

Extract at the **existing project root** `D:\IIT-B_Agentic_Ai\Capstone\AnalystDesk`, merging folders (do not replace the directories wholesale).

## Validation commands (Windows CMD, active conda environment Analystdesk)

```bat
python -m pytest -q tests\test_verified_coverage_selector.py
python -m pytest -q
```

The existing reference was **920 passed, 4 skipped**. With eight new tests, expect **928 passed, 4 skipped** if no other changes occur. Windows symlink skips are unchanged.

## Run full automatic selection

```bat
python tools\build_verified_coverage.py
```

The script first verifies and parses each of the **original 12 companies individually**. It checks *all three fiscal-year filings* before accepting a company. If a company fails — Oracle 2025 is already known to have an unsupported Item 8 layout — it tries the next previously unused replacement ticker from the **same sector**, obtains that company's three 10-K filings using the existing downloader, and runs the same checks. Candidates are tried in deterministic order; the script stops once there are 6 passing companies per sector.

### Initial group and **new-only** replacement pool

| Sector | Original six | Unused candidates (in attempted order) |
|---|---|---|
| Technology | MSFT GOOGL AAPL META NVDA ORCL | ADBE CRM CSCO QCOM INTU IBM TXN AMD INTC |
| Commerce/retail | WMT AMZN COST TGT HD LOW | BBY KR TJX ROST DG DLTR ULTA DKS ACI |

The candidate tickers are candidates **only**, not claims they have already passed validation, have supported SEC formats, or are fundamentally pure-play sector members. The downloader verifies filing availability and parser compatibility at runtime.

**No recycling:** No replacement ticker may equal any of the original twelve or duplicate an earlier replacement.

**Whole-company gating:** Even one missing or unparseable Item 8 excludes all three filings for that company. The script does not weaken the parser or make synthetic Item 8 text.

## Definition of `PARSER_VALIDATED`

- Exactly three annual filing records with distinct report dates and accessions.
- Local SEC HTML exists and is nontrivial; SHA256 is verified when supplied in the manifest.
- The current unchanged `process_manifest()` successfully extracts each 10-K separately.
- Parser summaries contain Items 1A, 7, 8 with meaningful section length.
- Every filing has passages for all three items.
- Every passage has consistent ticker, report date, unique ID, nonempty Unicode text, a SEC Archives URL, and matching accession metadata.
- Internal summary/passage counts reconcile; no duplicate passage IDs between accepted companies.

**Important:** Structural/provenance checks are necessary, not sufficient, to establish factual accuracy. The run produces `PARSER_VALIDATED`, not a blanket claim that all figures or boundaries were independently human-reviewed. Check representative passages before claiming accuracy in the presentation.

## Isolation and publication

Original, unmodified inputs:

```
evidence/10k_html_manifest.json
src/analyst_desk/document_parsing.py
data/parsed/10k_passages.jsonl
```

The workflow stages under:

```
data/verified_coverage/_work/<run-id>/
```

For *new candidates*, it starts `python -m analyst_desk.filings_cli --tickers <NEW> --years 3` with **that isolated directory as the subprocess working directory**. Thus the new candidate manifest and downloads are staged independently. The script copies only selected new SEC documents into the regular SEC cache (never overwrites an existing file).

Only when the required quota is achieved does it create a new immutable release:

```
data/verified_coverage/runs/<run-id>/10k_verified_manifest.json
data/verified_coverage/runs/<run-id>/10k_verified_passages.jsonl
data/verified_coverage/runs/<run-id>/10k_verified_parse_summary.json
data/verified_coverage/runs/<run-id>/selection_audit.json
```

It then atomically sets `data/verified_coverage/current.json` to the new release. Failed/insufficient runs leave the previous `current.json` intact and write `selection_audit_failed.json` into their staging directory.

**The existing Stage 2C index, Stage 3 MCP, Stage 4 agent and Chainlit are not switched to this new corpus automatically.** This deliberately keeps the regression baseline and production demo unchanged. Integrating and testing the expanded index is the subsequent stage.

## Possible results

- `SUCCESS: 12 companies, 36 filings, ... passages`: review release audit, then build an expanded independent hybrid index.
- `EXCLUDED: ORCL ... 2025-05-31 ... Item 8 ...`: expected known unsupported format, should try `ADBE` next.
- `EXCLUDED: ADBE ...`: automatic next candidate `CRM` attempted.
- `NOT PUBLISHED: ... queue exhausted`: no incomplete 12-company dataset is published. Inspect `selection_audit_failed.json` and choose additional **unused** same-sector tickers, or explicitly lower the quota to five per sector if the rubric permits 10 companies.

Optional, **only if 12 is infeasible and the assignment permits 10**:

```bat
python tools\build_verified_coverage.py --target-per-sector 5
```

This may select fewer of the original companies, and still demands **three validated filings per selected company**. We prefer the default 12-company target.

## Limitations and safety

- Assumes the existing working `filings_cli` uses paths relative to the process working directory (as suggested by its existing output); validates the separate manifest exists. If local configuration hard-codes project-root paths, adapt the isolation adapter before running live.
- SEC rate limits/terms, network outages, identifier changes and unavailable historic submissions may cause a replacement to fail; the selector records the reason and tries the next candidate.
- Do not enable new companies in the agent's allowlist until the separate index, retrieval quality checks, permissions, and UI behavior pass regression testing.
- The original `data/` directory is in the project's `.gitignore` according to the working baseline; generated corpus/releases should stay excluded from Git unless deliberately versioned through an approved artifact process.
- No LLM calls, report publication or external posts are made by this script.

# AnalystDesk Stage 4C — Rewriter summary formatting correction

## Why

The latest ADBE/LOW review has `REWRITER_SUMMARY_FORMAT_REJECTED`, with an
`UNCERTAIN` executive-summary claim and no accepted revisions. This code is
emitted when the model-generated summary text contains a line break **or** a
digit; the existing diagnostic cannot distinguish which occurred.

## Scope

- One source file only: `src/analyst_desk/stage4c3_revision.py`.
- Pure formatting: collapse whitespace/newline characters in a proposed
  executive-summary JSON **text** value without changing the words.
- Numeric content remains prohibited and now gets a separate diagnostic
  `REWRITER_SUMMARY_NUMBERS_REJECTED`.
- A repeated/unchanged claim still fails.
- Citation scopes, schema checks, 90–550-character summary constraints,
  quantitative evidence, independent Critic, hard blockers, and human approval
  are unchanged.

## Installation (CMD, project root)

```bat
python tools\apply_stage4c_summary_format_fix.py
python -m pytest -q tests\test_stage4c_summary_format_fix.py
```

The installer rejects unexpected source variants and backs up the original.
Do not rebuild or run the hosted LLM if installation/tests fail.

## After successful tests

```bat
set "ANALYSTDESK_VERIFIED_RELEASE_ID=20261101T100701Z_1219a55c"
set "GRAFANA_ADMIN_PASSWORD=<actual-password-or-nonempty-placeholder-for-API-only>"
docker compose up -d --build --no-deps analystdesk-api
curl.exe http://127.0.0.1:8000/healthz
```

Set the Grafana value in your terminal only; do not include secrets in logs.
Use the existing Chainlit process after API rebuild; restart UI if needed.

Re-running Writer/Critic makes paid model calls. Use a fresh run only once.
It may still block if the candidate summary includes digits, unsupported
inferences, or fails other evidence checks. A clear outcome is not guaranteed.

The final Critic property `review_disposition: REQUIRES_HUMAN_REVIEW` never
constitutes human approval. `semantic_entailment_checked: false` explicitly
means the report is not established as semantically entailed; the independent
Critic's model assessment is provisional and the report remains blocked.

# AnalystDesk Stage 4C Writer Length Fix

Scope: **one file**, `src/analyst_desk/stage4c1_writer.py`.

**Observed failure**: `Writer summary invalid after one schema correction: Writer executive summary must be 90-550 characters`. This occurs before Critic/Rewriter execution.

### Install from Windows CMD in project root

```bat
python tools\apply_stage4c_writer_length_fix.py
python -m pytest -q tests\test_stage4c_writer_length_fix.py
```

The installer rejects unknown source versions, backs up the previous file and syntax-checks the patch. It is idempotent.

### Change

- Writer instruction explicitly aims for **180–320 characters in the `executive_summary` string**, not the whole JSON response; keeps its separate actual hard requirement **90–550 characters**.
- Correction prompt repeats the length/unit target and requires separately attributed company claims.
- If length validation fails, the Writer error and second prompt give only the received **character count**, never the model's text or SEC evidence.
- No changes to the full validation contract, SEC identities, citations, report approval, financial values, or Critic verdicts.

### Rebuild after tests pass

```bat
docker compose up -d --build --no-deps analystdesk-api
docker compose exec -T analystdesk-api python -c "from analyst_desk.stage4c1_writer import OpenRouterReportWriter; print('STAGE4C_WRITER_READY')"
curl.exe http://127.0.0.1:8000/healthz
```

The environment variables required by `compose.yaml` must be set again if using a new CMD terminal. No need to recreate Chainlit.

Do **not** rerun paid LLM steps before the tests and Docker rebuild pass. One subsequent live check may still fail semantic Critic review; the fix does not assert 5/5 support.

### Installer V2 (previously patched Writer compatibility)
This version identifies the schema retry statement using the Python AST rather than
matching the exact wording. Earlier Stage 4C prompt patches can therefore coexist.
The installer still aborts before writing if the target code cannot be uniquely identified.
If V1 previously aborted, simply re-extract this ZIP with replacement and rerun the installer.

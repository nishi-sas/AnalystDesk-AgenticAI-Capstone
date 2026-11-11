# AnalystDesk — Opt-in 12-company runtime profile

## Purpose

Connect the **existing** Stage 4A planner and Stage 4B in-memory MCP research gateway to a **pinned, previously verified** 12-company SEC corpus and its separate hybrid index. No parser, retrieval engine, original corpus, Docker or Chainlit code is changed.

The opt-in environment variable is `ANALYSTDESK_VERIFIED_RELEASE_ID`. With it **unset**, existing behavior is preserved.

This is a local runtime integration increment. It **does not** claim the end-to-end approved-plan flow, offline EDGAR financial facts, Docker volume mapping or Chainlit are validated yet.

## Install (Windows CMD, `(Analystdesk)`)

1. Extract this archive into `D:\IIT-B_Agentic_Ai\Capstone\AnalystDesk` (merge folders).
2. `python tools\apply_verified_runtime_profile.py`
3. `python -m pytest -q tests\test_verified_runtime_profile.py`
4. `python -m pytest -q` (compare to previous `953 passed, 5 skipped`; +12 new tests expected)

## Opt-in local smoke check

Run without setting a persistent environment variable:

`python tools\smoke_verified_runtime.py --release-id 20261101T100701Z_1219a55c --ticker TGT --item 7`

This verifies:
- the original Stage 4A YAML config loads successfully;
- the 12-company allowlist matches the pinned release;
- Stage 4B's in-memory FastMCP gateway routes `search_passages` to the expanded corpus;
- filtered Target Item 7 hits return from the SEC index.

The smoke uses the MCP protocol directly to check configuration; **it does not bypass or replace role-policy checks in the normal approved agent research graph**.

## Subsequent real workflow (only after local smoke)

To opt in for a terminal session:

`set ANALYSTDESK_VERIFIED_RELEASE_ID=20261101T100701Z_1219a55c`

To return to legacy mode:

`set ANALYSTDESK_VERIFIED_RELEASE_ID=`

Ensure every process participating in planning, approval, and research uses the **same pinned release ID**. This avoids a moving pointer being silently updated between approval and research. For Docker/Chainlit, the release files must be mounted/readable in their runtime; a host CMD `set` does not propagate into existing containers. Do not alter Docker until a separate end-to-end smoke succeeds.

## Security and compatibility

- Rejects malformed or directory-traversal release IDs.
- Resolves corpus/index to the project's release root, refusing symlink escapes.
- Checks 12 companies, 3 periods each, each with Items 1A/7/8, unique canonical IDs, plausible SEC URLs and source hashes, valid text.
- The existing FilingsKnowledgeBase additionally checks index model and corpus digest during load.
- Does not download data, write new corpora, update `current.json`, or modify stored checkpoints.
- Profile is opted in with an explicit immutable release ID, **not** `current.json`.
- Financial XBRL facts for all 12 companies are **not** implied by having their 10-K HTML; that requires separate verification.

## Files included

`src/analyst_desk/verified_runtime_profile.py`, `tools/apply_verified_runtime_profile.py`, `tools/smoke_verified_runtime.py`, and `tests/test_verified_runtime_profile.py`.

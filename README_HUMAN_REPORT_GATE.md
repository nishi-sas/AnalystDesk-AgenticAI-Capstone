# AnalystDesk: Stage 4C local human report gate

**Purpose:** A *working*, auditable second human-in-the-loop gate in the local
Chainlit capstone prototype. Preserves Docker, the original 12-company corpus,
and every existing SEC/financial/Writer-Critic artifact. Does **not** silently
convert `UNCERTAIN` to `SUPPORTED`, call models, register or publish reports.

## Installation (Windows CMD)

1. Stop Chainlit using Ctrl+C; leave the Docker API running.
2. Extract this ZIP **into the AnalystDesk project root**, preserving the
   `tools`, `ui_patch` and `tests` directories.
3. Run in `(Analystdesk)`:

```bat
python tools\install_human_report_review.py
python -m pytest -q tests\test_phase10_human_report_review.py
```

4. Restart Chainlit in your `analystdesk-ui` environment:

```bat
conda activate analystdesk-ui
python -m chainlit run chainlit_app.py --host 127.0.0.1 --port 8001
```

A backup of the original `chainlit_app.py` is created under `backups/human_review_*`.
The installer checks the current app structure and rejects unfamiliar or partly
modified variants. It supports the UI **with or without** the preceding review
packet export patch. It may install `phase10_review_export.py` if missing.
**No Docker rebuild, model calls or dataset changes are needed.**

## See the gate using your EXISTING TGT/HD review — no model calls

In a fresh Chainlit chat, type:

```text
/review c2f3b8dc3d53480098f0cae2cbc2f9dc
```

This reopens the latest valid on-disk `ui_stage4c3_*_manifest.json` and checks
its draft SHA-256, Critic JSON, version chain and persisted Stage 4A approval.
For the saved TGT/HD output (`4/5`, `STAGE4C_REVIEW_BLOCKED`), Chainlit will
show **Request revision** and **Reject report**. **Approve** MUST be absent.

Click **Request revision**, then enter a confirmation like:

```text
REQUEST_REVISION | Course Reviewer | Executive summary makes an unsupported cross-company AI inference
```

The resulting receipt is in
`docker_runtime/human_review_decisions/HR-*.json`, and a Markdown copy is
attached in Chainlit. The note records a request; it does **not** run a model
or alter the original draft. To abort after clicking, type `/cancel`.

For a new *Critic-cleared* report with all supported claims and no blockers,
**Approve report locally** is available alongside Request revision and Reject.
Clicking only selects the decision. A second typed confirmation is required:

```text
APPROVE | Course Reviewer | I have checked the evidence, calculations and Critic conclusions
```

The decision receipt records the local report ID, approved research thread,
version, draft SHA-256, Critic JSON SHA-256, Critic status, reviewer's
self-declared identity, note and UTC timestamp. A file for the same exact
review version cannot be overwritten through the UI; changed review files
are rejected before recording a decision.

## Scope and safeguards

- The research-plan gate remains intact and authoritative; this is a **separate
  local report sign-off**.
- A blocked, uncertain, missing or incomplete Critic review **cannot be approved**.
- Reject/request revision can be recorded even if Critic review is blocked.
- A review result is rebound to persisted on-disk source artifacts immediately
  before a decision is written.
- Decisions persist outside the Chainlit session under `docker_runtime`.
- The browser UI in this demo has **no authenticated reviewer identity**.
  Reviewer names are self-declared; records are **not digitally signed**.
- This is **not** the native Phase 6 / Stage 4C-4 portal approval flow.
  It does not register a portal report, submit a report for review, change
  `human_report_approved` inside a Stage 4C manifest, or publish anything.
- Critic verdicts remain model evaluations, not independent proof of factual
  correctness or semantic entailment. Human sign-off is a capstone demo action.

## Acceptance sequence after installation

1. `/review c2f3b8dc3d53480098f0cae2cbc2f9dc` → blocked, no Approve.
2. Request revision → provide name/note → local decision receipt, no model call.
3. New pair from the verified cohort → plan approval → Docker research →
   Writer/Critic → review result and actions.
4. If all claims pass, approve locally and download receipt. Otherwise, request
   revision or reject; do not force a PASS.
5. Capture screenshots, review packet and decision receipt for the submission.

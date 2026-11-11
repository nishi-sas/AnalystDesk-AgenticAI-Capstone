# AnalystDesk — Stage 4C Writer / Critic integration in Chainlit

## Exactly what this adds

* Keeps the existing 12-company Docker research API, approved Stage 4A plan, offline evidence view and Chainlit workbench unchanged except for an additional opt-in action.
* After a successful research run, shows **Run Writer/Critic review (OpenRouter credits)**.
* On explicit click, invokes the **existing** `analyst_desk.stage4c3_cli run` in a temporary Docker container based on the **same image** as the running API, with its **same read-only SEC data, verified release, configuration and approved checkpoint volumes**. The original long-running Docker API is not modified or restarted.
* Temporarily mounts the host `.env` read-only so this *one-time review container* can call OpenRouter (the always-on API container remains secret-free). The host `evidence/` folder is mounted writable so review files survive removal of the temporary container.
* Validates that the Stage 4C manifest, draft SHA-256, Critic result and thread identity all agree, and that no human approval or publication occurred.
* Shows supported/total provisional Critic verdicts, hard blockers, review status and a downloadable **human-unapproved** reviewed report. The full Critic JSON is an attachment.
* Does **not** call the portal, submit, approve or publish any report. No hosted model calls run in the original offline path.

## Install

Extract ZIP into `D:\IIT-B_Agentic_Ai\Capstone\AnalystDesk` (merge directories, do not overwrite `chainlit_app.py` manually). Stop Chainlit (Ctrl+C) but **leave Docker running**.

In `(Analystdesk)` CMD, at project root:

```
python tools\apply_stage4c_chainlit_review.py
python -m pytest -q tests\test_phase10_review_bridge.py
```

The installer checks that your working `chainlit_app.py` is exactly the verified 12-company workbench release and saves a rollback copy under `backups/chainlit_before_stage4c_<timestamp>/`. It refuses unexpected modifications rather than overwrite them. **No Docker rebuild is needed.**

Restart Chainlit in its `analystdesk-ui` environment:

```
conda activate analystdesk-ui
python -m chainlit run chainlit_app.py --host 127.0.0.1 --port 8001
```

## Acceptance path

Open `http://127.0.0.1:8001`, select TGT/HD, ask your research question, approve the plan, run offline research, view evidence and draft, then **deliberately click** the new live review button if you agree to the associated provider/model usage and charges. The button is not automatic and uses the `.env` key in a *temporary* container.

Expected eventual phase for a fully supported review: `STAGE4C_READY_FOR_HUMAN_REVIEW`, with all claims `SUPPORTED`, zero blockers, model assessment performed, and downloadable `.md` file. If claims are uncertain or blocked, the UI should correctly say review blocked/incomplete and still show findings; never claim success from a blocked review.

If the temporary container fails, the UI prints a bounded error. The existing offline research and draft stay usable. Note that the Stage 4C CLI **reruns research** for its live synthesis/review; this is not merely reclassifying the offline draft.

### Operational boundaries

- The job requires a local `.env` with `OPENROUTER_API_KEY` and a provider model usable from Docker. **Never paste your key into chat.**
- The transient review container receives read access to the entire local `.env` (not the long-running FastAPI container). This is suitable for a controlled local prototype but a production system should use a restricted secret injection mechanism.
- Stage 4C3 may take longer and may incur OpenRouter charges. If free-tier/credits/network access fails, the UI must show an error, not fabricate review.
- Keep Docker loopback-bound, and do not run `docker compose down -v`.
- The UI makes a new revision prefix for each run so historical evidence files are never overwritten.
- No separate human report approval is implemented by this patch; a model-reviewed draft is *not* an approved or published report.

## Rollback

Stop Chainlit, copy the previous `chainlit_app.py` from the `backups/chainlit_before_stage4c_...` folder to project root, then delete `phase10_review_bridge.py`. Restart Chainlit. Docker and all other backend files remain untouched.

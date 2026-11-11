AnalystDesk Stage 4C Rewriter Prompt Fix
=====================================

PURPOSE
The Stage 4C-3 Rewriter previously instructed the model to preserve the phrase
that conclusions require independent human review inside SEC-backed narrative
claims. The independent Critic correctly found those claims unsupported by the
filings. It also found misattribution of company-specific controls and summary
risk themes lacking support from the permitted summary citations.

SCOPE
Changes ONLY prompt strings in src/analyst_desk/stage4c3_revision.py.
No change to evidence, source IDs, claim validation, revision graph, approval,
publication controls, or financial analysis. This is not a guaranteed semantic
pass; it aims to make model-generated revisions correctly evidence-scoped.

INSTALL
1. Extract this ZIP into the AnalystDesk project root (merging tools/ and tests/).
2. From the project root, run:
   python tools\apply_stage4c_rewriter_prompt_fix.py
   The script creates a timestamped copy under backups/.
3. Disable the pinned profile only while running full regression on temp-root
   fixtures, as the existing project tests rely on an unpinned default:
   set "ANALYSTDESK_VERIFIED_RELEASE_ID="
   python -m pytest -q tests\test_stage4c_rewriter_prompt_fix.py
   python -m pytest -q
4. Restore the verified release in the same CMD session:
   set ANALYSTDESK_VERIFIED_RELEASE_ID=20261101T100701Z_1219a55c
5. Run ONE new live attempt with a new output prefix:
   python -m analyst_desk.stage4c3_cli run --thread-id 5b27518e3ae44165b44c5275ecff1864 --max-revisions 1 --prefix evidence/58_stage4c3_tgt_hd_rewriter

The process may use paid OpenRouter calls; do not approve/publish blocked drafts.
Inspect review disposition, revision_count, revised_claim_ids, and final review.

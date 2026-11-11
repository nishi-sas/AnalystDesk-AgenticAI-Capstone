# AnalystDesk — Phase 6D Final Security Evidence and Residual-Risk Addendum

**Date:** 27 October 2026  
**Status:** **TECHNICAL VALIDATION COMPLETE — PASS_WITH_RESIDUAL_RISKS**  
**Security sign-off:** **PENDING_HUMAN_REVIEW**  
**Deployment ready:** **NO**  
**Report publication authorized:** **NO**  
**Companion document:** `security/threat_model.md` (do not delete or silently replace its original threat analysis)

> This addendum updates the historical 26 October threat model with *observed* 6D outcomes. Where the older threat model marks tests as pending, this dated acceptance addendum states the newer technical test results. It does not substitute for human risk acceptance or attestation of the actual deployment environment.

## 1. Final evidence summary

| Boundary / increment | Verified finding | Evidence |
| --- | --- | --- |
| User input and model gate, 6A | Real benign input passed; a direct injection was blocked by deterministic and Prompt Guard 2 checks | `79_phase6a3_openrouter_clean.txt`, `80_phase6a3_openrouter_attack.txt` |
| Pre-portal report, 6B-1 | Read-only output audits passed; no publication | `83_phase6b1_offline_audit.txt`, `84_phase6b1_live_output_safety.txt` |
| Deterministic red team, 6C-1 | 35/35 fixtures blocked; 0/8 benign blocked; **not** end-to-end | `87_phase6c_boundary_audit.txt` |
| LangGraph graph gate, 6C-2 | 11/11 user attacks stopped before planner; 8/8 benign reached pending review; defenses-off only isolated offline planner reachability | `90_phase6c2_graph_replay_console.txt` |
| External source tagging, 6C-2 | 10/10 labelled untrusted; tagging alone not enforcement | `91_phase6c2_external_audit.txt` |
| Live user-input model tests, 6C-2 | 11/11 attacks blocked; 0/8 benign false blocks; 19/19 valid request verdicts | `93_phase6c2_live_full.txt` |
| Retrieved-source quarantine, 6D-1 | 10/10 Writer and 12/12 Critic attacks quarantined before **stubbed** model; 5/5 benign accepted; zero real publication | `96_phase6d1_replay_console.txt` |
| Numeric integrity, 6D-2 | 4/4 SEC-cached financial metrics recalculated; GOOGL mixed concept still blocked | `103_phase6d2_real_audit_retry.txt` |
| Privilege/signature controls, 6D-3 | 31/31 passed in configured tool gateway and disposable SQLite; direct MCP production auth not attested | `104_phase6d3_controls.json`, `104_phase6d3_controls_console.txt` |
| Final evidence acceptance, 6D-4 | `PASS_WITH_RESIDUAL_RISKS`; 636 regression tests; no sign-off or deployment authorization | `105a_phase6d3_full_regression_retry.txt`, `106_phase6d4_acceptance.json`, `106_phase6d4_acceptance_console.txt` |

**Full regression baseline:** 636 passed in 13.49 seconds on Windows `(Analystdesk)`; 34 targeted 6D-3/6D-4 tests passed after explicit SQLite-connection cleanup fixed Windows `WinError 32`.

## 2. STRIDE threat status changes since the initial threat model

| Threat | Updated technical finding | Remaining exposure |
| --- | --- | --- |
| T03 / F-01, retrieved-source instruction injection | High-confidence synthetic injection patterns quarantined in real Writer/Critic functions before model stubs (22/22); prior 10/10 envelope tagging remains a separate result | Subtle semantic instructions against **live hosted** Writer/Critic not yet tested; do not claim absolute resistance |
| T04, unauthorized MCP privilege | Gateway role, tool allowlist and schema denials validated in selected tests; 31 control audit PASS | No authenticated direct MCP caller identity at server boundary for production |
| T05, computation/network escape | Unsafe tool surface absent from allowed agent-facing tools; negative policy checks passed | No hardened OS/network sandbox penetration test |
| T07 / F-02, numeric XBRL validity | Independent 4/4 arithmetic checks passed, with CIK, period, concept, unit and fact-origin consistency checks | Alphabet/GOOGL mixed revenue concepts remain unresolved; arithmetic check alone is not economic comparability |
| T08 / T09, forged/stale approvals or blocked publication | Wrong signer, tampered Ed25519 signature, stale revision/hash, editing after approval and active compliance blocker refused in disposable SQLite | Actual Windows private-key ACLs and production caller authorization not attested |
| T10 / T12, provider failures and model requirements | Fail-closed model verdict validation tested; actual provider configuration documented | NVIDIA Llama Guard 4 model did not complete live validation; Gemini on OpenRouter is a substitute, not equivalent |
| T11 / F-04, secret exports | `.env` is ignored; default key path outside project and test-only portal operations verified in selected controls | Scan **actual final submission ZIP**, logs and local ACLs before sharing |
| T14, defense-off measurement | Only isolated offline-planner reachability tested without gate | This is not real attack-success or data-exfiltration evidence |

## 3. Financial integrity and publication block

Four independently recomputed metrics from the cached SEC EDGAR source records:

| Company | Metric | Independently checked result | Status |
| --- | --- | ---: | --- |
| Microsoft | Operating margin | 46.78% | Verified same period |
| Microsoft | Revenue growth YoY | 17.79% | Verified same revenue tag |
| Alphabet | Operating margin | 32.03% | Verified same period |
| Alphabet | Revenue growth YoY | 15.09% | Verified arithmetic **only**; tag reconciliation required |

The GOOGL year-on-year comparison uses the different XBRL concepts `us-gaap:Revenues` and `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`. The original registered draft SHA-256 is `708108e7fd6e883a8438af7efefe3806431efc99fb846c1fb62565acef7ad6c9`. **The hard blocker `REVENUE_GROWTH_TAG_RECONCILIATION_OPEN` must remain in effect.** The audit did not register, approve, submit or publish this report. A future accounting reconciliation and separate approved report version are required before publication can be reconsidered.

## 4. Updated acceptance gate matrix

| Gate | Technical validation | Final disposition |
| --- | --- | --- |
| G1 Trust boundary/architecture | Documented; selected code and MCP call surfaces inspected | Technical documentation ready; real deployment access review pending |
| G2 Retrieved source injection | 22/22 quarantined before stub model; 5/5 benign allowed | **PASS within fixture scope**, residual live-semantic risk |
| G3 XBRL accuracy | 4/4 metrics recomputed; incorrect/uncached facts rejected | **PASS_WITH_BLOCKERS**, GOOGL report cannot publish |
| G4 Portal/signatures | 31 controls, invalid/stale/rejected publication denials | **PASS in isolated gateway/SQLite scope**; direct MCP auth pending |
| G5 Secrets/export | Limited selected checks | **OPEN** until actual final ZIP and sensitive-data scans complete |
| G6 Safety provider/rubric | Actual Gemini substitution documented | **OPEN** until rubric equivalence/exception decision |
| G7 Regression and evidence | 636/636 Windows tests; 6D4 acceptance receipt | **PASS** |
| G8 Human risk decision | No reviewer signature entered | **PENDING_HUMAN_REVIEW**; production deployment not authorized |

**Automatic technical evidence decision:** `PASS_WITH_RESIDUAL_RISKS`. This does not imply that every acceptance gate above is fully closed.

## 5. Residual-risk register and restrictions

| Priority | Residual exposure | Mandatory disposition |
| --- | --- | --- |
| P0 publication | Unreconciled GOOGL XBRL revenue concepts | Keep the existing draft **blocked**, do not silently change operands |
| P1 production access | Missing direct MCP production caller authentication | Local/demo scope only; authenticate/authorize each server boundary before deployment |
| P1 model semantics | Live hosted Writer/Critic semantic injection test gap | State scope clearly; do not claim general resistance |
| P1 model policy | Llama Guard 4 timeout; Gemini replacement | Disclose substitute and compare with assignment rubric |
| P1 execution isolation | Financial calculation subprocess not hardened OS/network sandbox | Do not claim verified sandbox isolation |
| P1 origin integrity | Local SEC SHA-256 and URL sidecars do not independently authenticate SEC origin | Implement trusted source attestation for production |
| P1 release confidentiality | Final ZIP not yet scanned; real Windows key ACLs unknown | Scan and document final archive before submission |

## 6. Security-owner and reviewer decision

**Reviewer / role:** _______________________________________  
**Review date:** __________________________________________  
**Git commit or release SHA-256:** _________________________  
**Decision:** `NOT REVIEWED` / `ACCEPTED WITH LIMITATIONS` / `BLOCKED`  
**Risk acceptance notes / restrictions:** __________________  
**Mitigation owner(s) and due date(s):** ___________________  

**Present state (27 October 2026):** Phase 6 implementation and selected technical security validation **COMPLETE**; human risk acceptance **NOT PERFORMED**; final submission archive scan **NOT PERFORMED**; deployment **NOT AUTHORIZED**; existing blocked report **NOT PUBLISHABLE**.

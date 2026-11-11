# AnalystDesk — Security Threat Model and Phase 6D Acceptance Record

**Document version:** 1.1 (regenerated 26 October 2026)  
**Project:** IIT Bombay Agentic AI Capstone — AnalystDesk  
**Document location:** `security/threat_model.md`  
**Assessment state:** **DRAFT / PHASE 6D OPEN — NOT ACCEPTED**  
**Evidence baseline:** 537/537 Windows tests passed after Phase 6C-2; see Section 7.  
**Scope:** Research on Microsoft (MSFT) and Alphabet (GOOGL), SEC EDGAR/XBRL ingestion and retrieval, LangGraph research workflow, restricted FastMCP services, human-in-the-loop review and mock Research Portal publication.

> **Read this first:** This is a threat model and security-acceptance checklist, **not a claim that the system has been penetration-tested**. Sections 6–8 distinguish observed outcomes from test gaps. No Phase 6D implementation or acceptance test is claimed complete by the existence of this document. A passing report *security audit* does not remove a financial/compliance hard blocker or authorize publication.

## 1. Purpose, assumptions and system limits

AnalystDesk takes an analyst research request, retrieves SEC filings and XBRL facts, performs approved calculations, synthesizes research and risks using multiple agents, generates and critiques a cited report, then registers a portal draft. Separately authorized human steps govern the plan and exact report version before any publication. The system uses a cached SEC corpus and configured hosted/local language models.

**Security properties sought:**

1. **Instruction integrity:** untrusted user input, retrieved filings, external articles and tool results cannot promote themselves into higher-priority instructions.
2. **Least privilege:** agents may invoke only allowed tools with validated arguments and authorized roles; restricted financial computation is not unrestricted shell execution.
3. **Confidentiality:** API credentials, private/watchlist information and internal approval material are not leaked through prompts, generated reports, traces or tool outputs.
4. **Financial integrity:** reported facts and derived metrics retain verifiable accession/concept/unit/period/operand provenance; citation existence alone is not proof of numeric accuracy.
5. **Human authority and publication integrity:** no forged, stale, mismatched, self-approved or unreviewed report can be published; edits invalidate previous approvals.
6. **Auditable failure:** model outages and malformed verdicts fail closed, with security denials kept distinct from **successful model classification**; tests retain safe evidence.

**Excluded/not demonstrated:** real brokerage/trading, an unrestricted OS/network sandbox, real watchlist exfiltration testing, general web crawling attack resistance, production hardening of model/provider accounts, or an end-to-end penetration test of all components. Claims below are limited to tested boundaries.

## 2. Architecture and data-flow boundaries

```text
Analyst / UI
    | request + analyst_id                 [TB-1: untrusted user boundary]
    v
Deterministic input gate + scope model + local Prompt Guard 2 + safety model
    | accepted request
    v
LangGraph planner --- checkpointed human PLAN review
    |
    +--> SEC EDGAR / filings KB / hybrid retrieval [TB-2: retrieved content]
    +--> restricted financial calculation MCP       [TB-3: tool permissions]
    |
    v
Evidence aggregation -> Writer -> Compliance Critic (bounded revisions)
    |                         [TB-4: generated claims + financial facts]
    v
Mandatory pre-portal output gate / privileged MCP argument checks
    |                         [TB-5: portal write boundary]
    v
Mock Research Portal DRAFT (content SHA-256 + revision + source registration)
    |
    v
Checkpointed human REPORT review -> Ed25519-bound authorization
    |                         [TB-6: human/signature boundary]
    v
Publication action (only if approved, current and blocker-free)

Side boundary [TB-7]: .env/model providers, caches, host filesystem, logs,
  evaluation fixtures, persisted LangGraph checkpoints and portal SQLite DB.
```

| Boundary | Trust level / entry point | Attacker opportunity | Existing control and evidence status |
| --- | --- | --- | --- |
| TB-1 User → planner | User is not an authority over system instructions | Direct injection, out-of-scope analysis, unsafe request | **Tested** deterministic + three model adapters, strict gate before planner (6A, 6C-2) |
| TB-2 SEC/other text → agents | Retrieved passages and article bodies are **data**, even if from reputable sources | Poisoned passages, forged role directives, malicious links, answer contamination | **Partial**: 10/10 labelled `UNTRUSTED_DATA`; actual Writer/Critic resistance **not tested** |
| TB-3 Agent → MCP service | Agent outputs do not grant tool privileges | Unauthorized tool/role/schema, code/network execution, data access | **Tested at policy boundary** for restricted tools and portal gateway; OS sandbox penetration **not demonstrated** |
| TB-4 Facts → claims | XBRL/citation identifiers are evidence pointers, not correctness certificates | Wrong values, tag/period/unit mismatch, plausible fabricated percentages | **Partial**: identity/provenance checks and critic; independent numeric reconciliation **not demonstrated** |
| TB-5 Writer/Critic → portal | Generated Markdown is untrusted until checked | Injection in report, HTML/remote content, secrets, unsupported advice, self-approval | **Tested** mandatory deterministic pre-portal gate and optional live safety audit (6B-1) |
| TB-6 Reviewer → publish | Only distinct authorized human and server-trusted signing record approve | Forged/stale signature, approval after edit, forced publish | **Tested** hash/revision/Ed25519 stale-approval rejection (Phase 5); deployment key custody not audited |
| TB-7 App → host/providers | Runtime/provider secrets and evidence paths have separate access | Credential leaks, log disclosure, model outages, insecure mounts | **Partial**: fail-closed model errors; host/deployment controls need review |

## 3. Assets and adversary model

| Asset | Sensitivity/importance | Main failure consequence |
| --- | --- | --- |
| `.env` credentials and provider API keys | Confidential | Account misuse, data exposure and API charges |
| SEC source cache, accession/fact metadata and citations | Integrity-critical | Unsupported/inaccurate research presented as sourced |
| XBRL values, unit and fiscal-period mapping | Integrity-critical | Incorrect numerical comparisons and financial conclusions |
| Private research/watchlist or analyst identifiers, if configured | Confidential | Unauthorized disclosure; **real exfiltration not demonstrated** |
| LangGraph checkpoint data, plans, drafts and critic decisions | Integrity- and confidentiality-critical | Workflow tampering, injected lessons or bypassed review |
| Portal SQLite state, report SHA/revision and Ed25519 signature | High integrity | Fraudulent or premature publication |
| Evaluation fixtures, logs and golden data | Integrity/confidentiality | Inflated measurements, contamination or leak |

**Potential attacker positions:** (a) direct requester supplying a malicious prompt; (b) external source/retrieved-document author embedding instructions in otherwise relevant SEC-style content; (c) compromised/malformed model or MCP tool response; (d) agent producing unauthorized tool arguments; (e) local insider with improper access to files, configuration or approval records. No assertion is made that all positions have been simulated end-to-end.

**Key assumptions requiring confirmation:** SEC cache provenance is genuine and immutable enough for the test; the allowlist is enforced where calls occur; signing keys are not available to the Writer/LLM; test-only stub providers cannot appear in production; portal operations validate trusted state independently of agent text; secrets and evaluation gold data are not included in deliverable bundles.

## 4. Threat analysis (STRIDE-informed)

Severity is *qualitative* (Critical/High/Medium) and denotes potential impact, not an observed exploit or measured probability. `Verified` means only the stated test boundary was exercised; it does not mean universal security.

| ID | STRIDE class | Threat / attack path | Severity | Mitigation or current control | Status and required follow-up |
| --- | --- | --- | --- | --- | --- |
| T01 | Tampering/Elevation | User prompt attempts to override system instructions before planning | High | Deterministic injection detection + Prompt Guard 2, strict LangGraph pre-planner gate | **Verified on selected cases**: live direct-injection example; graph 11/11 blocked; broader bypasses still possible |
| T02 | Elevation/Information disclosure | User requests out-of-scope stock advice or protected watchlist data | High | Scope/advice filters, tool permission policy | **Verified at configured boundaries**; actual private-data exfiltration not exercised |
| T03 | Tampering | Retrieved SEC/article text impersonates a system/developer message and steers Writer/Critic | **High** | `UNTRUSTED_DATA` envelope; output gate provides some defense in depth | **OPEN / P0**: 10/10 merely tagged, 0 ingestion blocked; perform nonpublishing Writer/Critic traversal |
| T04 | Elevation | Agent requests unknown MCP tool, forged portal role or unexpected arguments | High | Approved tool manifest and schema/role validation at gateway | **Verified with policy fixtures**; review deployed tool credentials/ACLs |
| T05 | Elevation/Information disclosure | Agent runs arbitrary code or opens uncontrolled outbound network connection | High | Calculation MCP exposes approved formulas, not general-purpose code execution | **PARTIAL / P1**: deny policy tested; OS/network sandbox isolation not penetration-tested |
| T06 | Information disclosure | Output report contains API key, private detail, HTML/script, remote link or unsafe advice | High | Pre-portal output audit, secret/pattern and active-content filters, optional live safety model | **Verified for tested patterns**; add runtime log redaction/secret-scanning verification |
| T07 | Tampering | XBRL result uses a real citation but wrong values, units or fiscal years | **High** | Fact IDs and source provenance; upstream calculations and critic | **OPEN / P0**: citation identity does not prove numeric claim correctness; add independent recomputation |
| T08 | Spoofing/Repudiation | Report approval forged, replayed after edit, or signed for a different revision | **Critical** | Server-validated Ed25519, draft SHA/revision binding, two HITL checkpoints | **Verified with Phase 5 stale-approval and rejection tests**; key-management review remains |
| T09 | Elevation/Tampering | Unresolved compliance blocker silently cleared or bypassed to publish | **Critical** | Critic/portal hard-block logic and publisher authorization | **Observed fail-closed**: existing report remains DRAFT with blocker; negative end-to-end publication test needed in 6D |
| T10 | Denial of service | Model safety provider timeout or malformed response is treated as safe | High | Strict classifier schemas and fail-closed policy; error ≠ valid verdict | **Verified in tests**; provider outage can deny legitimate work, monitor latency |
| T11 | Information disclosure/Tampering | Logs, exports or submission ZIP expose secrets or evaluator gold files | High | Local `.env` separation and evidence receipts; no raw payloads intended | **OPEN / P1**: run repository/ZIP secret scan and check `.gitignore`, mounts, logs |
| T12 | Compliance / operational | Gemini OpenRouter substituted for specified Llama Guard 4 | Medium | Explicit provider configuration and truthful record of attempted NVIDIA deployment | **OPEN / P1**: review rubric and disclose substitution; model equivalence must not be implied |
| T13 | Tampering | Injected external passage or agent output includes fake approval or meta-instructions in final note | High | Output gate (`NO_INSTRUCTION_HIJACK_IN_REPORT`, `REVIEW_NOT_SELF_APPROVED`) + true signed portal gate | **Verified at output policy boundary**, downstream behavior not fully tested |
| T14 | Repudiation | Defenses-off simulation presented as real exploitation | Medium | Explicit run modes and receipt wording | **Controlled by reporting**: Phase 6C-1 counterfactual unexecuted; 6C-2 offline planner reachability ≠ attack success |

## 5. Verified controls and *precise* measurements (26 Oct 2026)

| Security layer | Windows test / run | Observed result | What it does **not** prove |
| --- | --- | --- | --- |
| Input guardrails 6A | Targeted `77a`; regression `78a`; live `79`, `80` | **43 targeted / 439 regression passed**. Clean request PASS; malicious request BLOCKED by deterministic and Prompt Guard 2 | No proof about malicious retrieved content |
| Pre-portal output/tool 6B-1 | `81`, `82`, `83`, `84` | **36 targeted / 475 regression passed**. Offline and model output audits PASS; zero portal registration/approval/publication in audit | No XBRL-value accuracy or publishing permission granted |
| Deterministic red team 6C-1 | `85`, `86`, `87` | **48 targeted / 523 regression passed**. **35/35** fixtures blocked, **0/8** benign falsely blocked | Not end-to-end, no live models/network sandbox; defense-off not executed |
| Checkpointed graph replay 6C-2 | `88`, `89`, `90` | **14 targeted / 537 regression passed**. **11/11** input attacks stopped before planner, **8/8** benign reached *pending* review | Planner is offline; model decisions are stubs; does not publish or test Writer |
| External source envelope | `91` | **10/10** labelled untrusted; **0** blocked at ingestion | Downstream resilience **explicitly unverified** |
| Live model smoke 6C-2 | `92` | **6/6** adversarial blocked, **0/4** benign blocked, **10/10** request verdicts valid | Only user-input classifier boundary |
| Live model full 6C-2 | `93` | **11/11** adversarial blocked, **0/8** benign blocked, **19/19** request verdicts valid | Not full-agent attack success/defense rate |
| Signed review and portal | Existing Phase 5 regression | Stale signature/hash after edit refused; blocked draft does not publish | No production signing-key/access audit |

**Live blocking attribution:** `SCOPE_MODEL=5`, `INJECTION_MODEL=2`, `SAFETY_MODEL=6` are overlapping counts across the 11 attacks. Their sum **is not** a count of distinct attacks.

**Defenses-off interpretation:** The 6C-1 report states `executed=false`. In 6C-2, 10 inputs were eligible to reach an isolated offline planner without the input gate; the real agent, MCP network and portal were **not** executed. This is a *reachability* measure, not exploitation or exfiltration.

**Model implementation:** OpenRouter `openai/gpt-5-mini` for scope, local Meta Prompt Guard 2 86M for injection, and OpenRouter Gemini 3.1 Flash-Lite for safety. **Gemini is not Meta Llama Guard 4**; NVIDIA-hosted Llama Guard 4 inference timed out in earlier live attempts. In these runs model errors were not counted as valid security verdicts.

## 6. Known findings requiring Phase 6D engineering

### F-01 — Retrieved-content instruction injection (P0, OPEN)

**Observation:** Ten external-content fixtures were wrapped as `UNTRUSTED_DATA`, but `ingestion_blocked=0` and `downstream_resilience_verified=false`. A filing passage can be factually relevant while carrying malicious agent instructions. The label is not a security enforcement boundary by itself.

**Safe acceptance experiment:** Use a controlled *fixture* containing a legitimate-looking SEC excerpt plus an obviously artificial instruction. Feed it through the actual Writer and Critic with the normal prompt hierarchy; use a scratch checkpoint and stubbed/nonpublishing portal. Assess (a) whether instruction text is obeyed, repeated as authoritative or merely cited as untrusted; (b) whether an output guard detects forbidden report content; (c) whether portal creation is prevented on failure. Collect redacted per-case receipts with prompt/template version, attack ID, outcome and zero publication side effects. Include benign matched controls to quantify false blocks. If unresolved, retain this as high residual risk and restrict deployment.

### F-02 — Numeric XBRL integrity and tag mismatch (P0, OPEN)

**Observation:** A prior generated report carries `REVENUE_GROWTH_TAG_RECONCILIATION_OPEN`. In the reviewed GOOGL revenue growth calculation, current-period `us-gaap:Revenues` and previous-period `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` are not identical concepts. The previously reported ~15.09% figure must **not** be silently declared reconciled. The Phase 6B output audit verifies fact-ID presence, not that calculations faithfully use equivalent source concepts/units/periods.

**Acceptance experiment:** Take one current report figure and independently extract source `CIK`, 10-K accession, `us-gaap` concept, form, unit, exact period start/end and values; recompute the derived metric with approved deterministic code, including rounding; compare against the report. Reject mismatched concepts or incomparable periods unless an explicitly reviewed mapping/normalization is documented. Capture the mismatch and maintain the blocker if unresolved. Also test a forged valid-looking citation ID paired with an incorrect numeric value: the required cross-check must reject it.

**Publication invariant:** The registered SHA-256 `708108e7fd6e883a8438af7efefe3806431efc99fb846c1fb62565acef7ad6c9` and 22 registered sources were successfully *audited* in Phase 6B. That audit did **not** approve or publish the report. The existing reconciliation blocker remains active unless separately and correctly resolved.

### F-03 — Network/compute and privilege hardening (P1, PARTIAL)

**Observation:** Denial of unknown tool calls and restricted approved calculations are verified. This is not proof of filesystem, shell or network isolation under a hostile workload.

**Acceptance:** Inspect actual deployed MCP manifests and role binding; test refused unknown tool, extraneous parameters, unauthorized portal write and missing/stale review with safe fixtures. Record whether a separate compute worker is configured with no secrets/no network and resource limits. If no unrestricted executor exists, state so; do not claim to have penetration-tested one.

### F-04 — Secrets, provider behavior and capstone rubric (P1, OPEN)

**Observation:** Model-provider timeout behavior is fail-closed; actual final safety model is Gemini on OpenRouter rather than Llama Guard 4. Key custody, submission ZIP and model-routing metadata have not yet had formal 6D acceptance review.

**Acceptance:** Check `.gitignore` and package contents for `.env`, API keys, `.sqlite3` production state and evaluation gold data. Review log/error-message redaction. Confirm Llama Guard 4 requirement from the assessor's rubric and log substitution with rationale, or successfully validate the prescribed model. Record model IDs/provider, not actual keys. Do not disable TLS checks or bypass fail-closed behavior to produce passing metrics.

## 7. Evidence register (existing files in Windows `evidence/`)

| Evidence file | Meaning |
| --- | --- |
| `77a_phase6a3_targeted_retry.txt` / `78a_phase6a3_full_regression_retry.txt` | Input guardrail tests: 43 and 439 passed |
| `79_phase6a3_openrouter_clean.txt` / `80_phase6a3_openrouter_attack.txt` | Live clean and malicious input receipts |
| `81_phase6b1_targeted.txt` / `82_phase6b1_regression.txt` | Pre-portal security: 36 and 475 passed |
| `83_phase6b1_offline_audit.txt` / `84_phase6b1_live_output_safety.txt` | Pre-portal read-only output audits, blocker preserved |
| `85_phase6c_targeted_tests.txt` / `86_phase6c_full_regression.txt` | Boundary-suite 48 and 523 passed |
| `87_phase6c_boundary_audit.txt` / `85_phase6c_redteam_results.json` | 35 adversarial/8 benign policy receipt |
| `88_phase6c2_targeted.txt` / `89_phase6c2_full_regression.txt` | 14 and 537 passed |
| `90_phase6c2_graph_replay_console.txt` / `88_phase6c2_graph_replay.json` | Input graph replay, pending review and offline baseline |
| `91_phase6c2_external_audit.txt` / `90_phase6c2_external_envelope.json` | 10/10 external texts tagged; Writer not verified |
| `92_phase6c2_live_smoke.txt` / `89_phase6c2_live_smoke.json` | Live smoke input classification |
| `93_phase6c2_live_full.txt` / `89_phase6c2_live_full.json` | Live full input classification, 19 valid verdicts |
| Phase 5 report-approval test logs | Invalidated-signature, edited-report and blocked-publication cases |

*These are paths in the user's local project. They have been reported in the current project session; this regenerated Markdown itself does not independently re-run those tests.*

## 8. Phase 6D final acceptance matrix (complete only after evidence)

| Gate | Minimum evidence required | Current decision |
| --- | --- | --- |
| G1 Document and validate trust boundaries | Reviewer confirms code-level flow + MCP privileges | **PENDING** |
| G2 Retrieved-passage attack traversal | Nonpublishing Writer/Critic adversarial + benign replay; result and blocking behavior | **NOT TESTED** |
| G3 Financial recomputation | At least one exact XBRL concept/unit/period/value reconciliation and forged-number negative test | **NOT TESTED** |
| G4 Portal authorization invariants | Signed-approval, stale hash/revision, wrong role, hard blocker negative tests | **PARTIAL: earlier Phase 5/6B evidence** |
| G5 Secrets and packaging | `.env`/logs/ZIP review and positive evidence of exclusions | **PENDING** |
| G6 Model substitution | Rubric checked; Llama Guard 4 substitution documented or model validated | **PENDING** |
| G7 Regression and metrics | Full Windows pytest (baseline 537), 6D tests, red-team receipts reviewed | **BASELINE PASSED; 6D PENDING** |
| G8 Residual risk decision | Owner, priority, mitigation/defer rationale, reviewed date, decision | **PENDING** |

**Acceptance rule:** Mark Phase 6D **COMPLETE** only when gates G1–G8 have evidence and an explicit reviewer decision. A gap may be accepted with limitations only when the reviewer explicitly records the risk and constrains deployment; critical publication bypass or undisclosed numerical-integrity failures must remain blocking. For the capstone, a DRAFT/NOT ACCEPTED record is more accurate than an unsupported PASS.

## 9. Residual risk register and ownership

| Risk ID | Owner (assign before final) | Priority | Required action | State |
| --- | --- | --- | --- | --- |
| R01 / F-01 | Security & agent-workflow lead — **TBD** | P0 | Test poisoned SEC passage through Writer/Critic and preserve safe output | OPEN |
| R02 / F-02 | Quant/data-evidence lead — **TBD** | P0 | Reconcile GOOGL concepts, values, units and periods; retain blocker until justified | OPEN |
| R03 / F-03 | MCP/infrastructure lead — **TBD** | P1 | Validate deployed allowlist/roles and state actual isolation, without overclaim | PARTIAL |
| R04 / F-04 | Security/deployment lead — **TBD** | P1 | Secret-scan logs/submission and document provider/rubric deviation | OPEN |
| R05 | Human-review/portal lead — **TBD** | P1 | Repeat final negative no-publish acceptance and confirm key protection | PARTIAL |
| R06 | Evaluation owner — **TBD** | P2 | Maintain explicit denominator, mode and provenance for every red-team rate | CONTROLLED IN CURRENT REPORT |

## 10. Final reviewer decision (not yet recorded)

**Reviewer / role:** _______________________________  
**Review date (YYYY-MM-DD):** _____________________  
**Evidence commit / release ZIP SHA-256:** ______________________________  
**Decision:** `NOT REVIEWED` / `ACCEPTED WITH LIMITATIONS` / `ACCEPTED` / `BLOCKED`  
**Open critical/high findings and decision rationale:** ______________________________  
**Deployment restriction or mitigation owner/date:** ______________________________

**Current document decision (26 October 2026): `NOT REVIEWED — PHASE 6D OPEN`.** Phase 6A, 6B-1 and 6C demonstrate successful checks at specified boundaries; Phase 6D must still test retrieved-content traversal, numeric correctness and remaining acceptance items. No automated step may sign this section or promote a blocked report to publication.

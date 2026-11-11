"""Phase 8C pilot: frozen-evidence Stage 4C architecture comparison.

C0: deterministic report renderer; C1: one Writer (no iterative feedback);
C2: Writer + independent Critic + bounded targeted Rewriter. C0/C1 are
post-hoc audited (review only). This is NOT full-pipeline agent comparison or
an independent fact/entailment score. No publication, portal write or approval.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from .stage4c1_writer import produce_draft, validate_writer_input
from .stage4c2_critic import review_report
from .stage4c3_revision import run_revision_loop

BLOCKER = 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'
CONFIGS = ('C0', 'C1', 'C2')
UPSTREAM_MODES = ('synthesized', 'audited')


class ArchitectureEvalError(ValueError):
    pass


# SECURITY: These are static diagnosis codes. Never concatenate raw exceptions,
# LLM output, source text, HTTP response bodies, URLs or credentials into logs.
def _failure_code(exc: Exception) -> str:
    if isinstance(exc, ArchitectureEvalError):
        message = str(exc)
        if message == 'DOWNSTREAM_MODEL_CALL_LIMIT_EXCEEDED':
            return 'MODEL_CALL_BUDGET_EXHAUSTED'
        if message.startswith('FINANCIAL_SECTION_'):
            return 'FINANCIAL_SECTION_INTEGRITY'
        if message.startswith(('FROZEN_', 'ARMS_', 'UNAPPROVED_')):
            return 'EVALUATION_INVARIANT_FAILED'
        return 'EVALUATION_CONTRACT_FAILED'
    klass = type(exc).__name__
    model_codes = {
        'AuthenticationError': 'MODEL_AUTHENTICATION_ERROR',
        'PermissionDeniedError': 'MODEL_PERMISSION_DENIED',
        'RateLimitError': 'MODEL_RATE_LIMIT',
        'APITimeoutError': 'MODEL_TIMEOUT',
        'APIConnectionError': 'MODEL_CONNECTION_ERROR',
        'BadRequestError': 'MODEL_BAD_REQUEST',
        'InternalServerError': 'MODEL_SERVER_ERROR',
        'APIStatusError': 'MODEL_API_STATUS_ERROR',
    }
    if klass in model_codes:
        return model_codes[klass]
    if klass == 'ResearchError':
        message = str(exc)
        if message.startswith('LLM synthesis invalid after one correction:'):
            return 'SYNTHESIS_SCHEMA_REJECTED'
        if message.startswith('Writer summary invalid after one schema correction:'):
            return 'WRITER_SCHEMA_REJECTED'
        if message.startswith('Critic JSON invalid after bounded repair:'):
            return 'CRITIC_SCHEMA_REJECTED'
        if message.startswith('Rewriter') or message.startswith('Revision'):
            return 'REVISION_CONTRACT_FAILED'
        if message.startswith('Writer'):
            return 'WRITER_INPUT_OR_OUTPUT_REJECTED'
        if message.startswith('Critic'):
            return 'CRITIC_SOURCE_OR_OUTPUT_REJECTED'
        return 'RESEARCH_CONTRACT_FAILED'
    if 'MCP' in klass or 'ToolError' in klass:
        return 'MCP_SERVICE_ERROR'
    return 'UNCLASSIFIED_OPERATION_ERROR'


def _stage_error(stage: str, exc: Exception) -> ArchitectureEvalError:
    # Every stage is an authored constant, not a value derived from an exception.
    known = {
        'B3_SHARED_UPSTREAM', 'DOWNSTREAM_MCP_SETUP',
        'C0_DRAFT', 'C0_CRITIC', 'C0_INTEGRITY',
        'C1_DRAFT', 'C1_CRITIC', 'C1_INTEGRITY',
        'C2_WRITER_CRITIC_REVISION', 'C2_INTEGRITY',
    }
    if stage not in known:
        stage = 'UNKNOWN_STAGE'
    return ArchitectureEvalError('STAGE=' + stage + ';CODE=' + _failure_code(exc))


def evidence_digest(evidence: dict) -> str:
    fields = ('financial_comparability', 'risk_evidence_citations', 'warnings',
              'citation_count', 'xbrl_fact_count', 'synthesis')
    if not isinstance(evidence, dict) or any(k not in evidence for k in fields):
        raise ArchitectureEvalError('FROZEN_EVIDENCE_INCOMPLETE')
    blob = json.dumps({k:evidence[k] for k in fields},sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


# Stage 4C uses human-approved outline headings; do NOT assume a fixed title.
# Match the deterministic SEC metric table, not a human-selected section label.
_FINANCIAL_HEADER = '| Company | Fiscal year ended | Operating margin | Revenue growth YoY | Growth-tag status |'
_FINANCIAL_SECTION_HEAD = re.compile(r'(?m)^## [^\n]+\n\n')


def financial_digest(markdown: str) -> str:
    """Fingerprint the *entire* canonical financial subsection, independent of title.

    The Writer can map the financial table into any approved report-outline heading.
    Only a single top-level section beginning with the exact deterministic table
    header is accepted. We hash its complete text, including source operands,
    classification, and reconciliation warning. We fail closed on missing,
    duplicate, displaced, or incomplete sections.
    """
    if not isinstance(markdown, str):
        raise ArchitectureEvalError('DRAFT_INVALID')
    normalized = markdown.replace('\r\n', '\n')
    headings = list(_FINANCIAL_SECTION_HEAD.finditer(normalized))
    matches = []
    for i, heading in enumerate(headings):
        stop = headings[i + 1].start() if i + 1 < len(headings) else len(normalized)
        section = normalized[heading.end():stop].strip()
        if _FINANCIAL_HEADER in section:
            matches.append(section)
    if len(matches) != 1:
        raise ArchitectureEvalError('FINANCIAL_SECTION_MISSING' if not matches else
                                    'FINANCIAL_SECTION_AMBIGUOUS')
    section = matches[0]
    if (not section.startswith(_FINANCIAL_HEADER) or
            section.count(_FINANCIAL_HEADER) != 1 or
            '**XBRL fact operand IDs**' not in section or
            'All percentages above come from' not in section or
            'TAG_RECONCILIATION_REQUIRED' not in section):
        raise ArchitectureEvalError('FINANCIAL_SECTION_INCOMPLETE')
    return hashlib.sha256(section.encode('utf-8')).hexdigest()


def _counts(review: dict) -> dict:
    if not isinstance(review,dict) or review.get('status')!='PASS' or not isinstance(review.get('findings'),list):
        raise ArchitectureEvalError('CRITIC_REVIEW_INVALID')
    return {v:sum(f.get('verdict')==v for f in review['findings'])
            for v in ('SUPPORTED','UNSUPPORTED','UNCERTAIN','NOT_REVIEWED')}


def _verify(plan, evidence, thread_id, allowed, budget):
    if sorted(plan.get('companies',[]))!=['GOOGL','MSFT']:
        raise ArchitectureEvalError('ONLY_APPROVED_MSFT_GOOGL_PILOT_SUPPORTED')
    if not isinstance(thread_id,str) or len(thread_id)!=32 or any(c not in '0123456789abcdef' for c in thread_id):
        raise ArchitectureEvalError('INVALID_THREAD_ID')
    validate_writer_input(plan,evidence,thread_id=thread_id,allowed=allowed,budget=budget)
    if 'GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED' not in evidence['warnings']:
        raise ArchitectureEvalError('REVENUE_TAG_BLOCKER_MISSING')


def _summarize_arm(config: str, draft: dict, review: dict, *, revisions: int, status: str,
                   elapsed_ms: float, before_sha: str, finance_sha: str, version_count:int) -> dict:
    if (draft.get('status')!='PASS' or draft.get('human_report_approved') is not False or
            draft.get('publication_performed') is not False or
            review.get('human_report_approved') is not False or review.get('publication_performed') is not False or
            BLOCKER not in review.get('hard_blockers',[]) or
            'GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED' not in draft['draft_markdown']):
        raise ArchitectureEvalError('UNAPPROVED_DRAFT_OR_BLOCKER_INVARIANT_BROKEN')
    current_financial=financial_digest(draft['draft_markdown'])
    if current_financial != finance_sha:
        raise ArchitectureEvalError('FINANCIAL_SECTION_CHANGED_ACROSS_ARMS')
    return {
        'configuration':config, 'status':status, 'wall_latency_ms':round(elapsed_ms,3),
        'revisions':revisions, 'draft_version_count':version_count,
        'final_draft_sha256':hashlib.sha256(draft['draft_markdown'].encode('utf-8')).hexdigest(),
        'financial_section_sha256':current_financial, 'input_evidence_sha256':before_sha,
        'source_citation_count':draft['source_citation_count'], 'xbrl_fact_count':draft['xbrl_fact_count'],
        'critic_claim_count':review['claim_count'], 'critic_verdicts':_counts(review),
        'canonical_passages_checked':review['canonical_passages_checked'],
        'hard_blockers':review['hard_blockers'],
        'independent_human_entailment_judgment':False,
        'human_report_approved':False, 'publication_performed':False,
    }


async def paired_downstream_evaluation(plan:dict, evidence:dict, *, thread_id:str,
                                        allowed:tuple[str,...], budget:int, call,
                                        writer_factory, critic_factory, rewriter_factory,
                                        max_revisions:int=2, measurement_probe=None,
                                        capture_review_materials:bool=False) -> dict:
    """Evaluate all arms with a shared immutable input; external model calls injectable.

    `writer_factory`, `critic_factory`, `rewriter_factory` take configuration name.
    The critic is used after C0/C1 as a diagnostic only (never as an actor).
    """
    if type(max_revisions) is not int or max_revisions not in (0,1,2):
        raise ArchitectureEvalError('INVALID_REVISION_LIMIT')
    _verify(plan,evidence,thread_id,allowed,budget)
    initial=evidence_digest(evidence)
    frozen_plan=deepcopy(plan); frozen_evidence=deepcopy(evidence)
    results=[]
    review_materials=[]
    financial_sha=None
    for mode in CONFIGS:
        stage=mode+'_DRAFT' if mode!='C2' else 'C2_WRITER_CRITIC_REVISION'
        try:
            t0=perf_counter()
            usage_before=measurement_probe() if measurement_probe is not None else None
            plan_copy=deepcopy(frozen_plan); evidence_copy=deepcopy(frozen_evidence)
            if mode == 'C2':
                result=await run_revision_loop(plan_copy,evidence_copy,thread_id=thread_id,
                    allowed=allowed,budget=budget,call=call,writer=writer_factory(mode),
                    critic=critic_factory(mode),rewriter=rewriter_factory(mode),
                    max_revisions=max_revisions)
                draft=result['final_draft']; review=result['final_review']; revisions=result['revision_count']
                count=len(result['versions']); status=result['phase']
            else:
                writer=None if mode=='C0' else writer_factory(mode)
                draft=produce_draft(plan_copy,evidence_copy,thread_id=thread_id,
                                    allowed=allowed,budget=budget,writer=writer)
                stage=mode+'_CRITIC'
                # This audit is NOT feedback to the C0/C1 production configuration.
                review=await review_report(plan_copy,evidence_copy,draft,thread_id=thread_id,
                    allowed=allowed,budget=budget,call=call,model=critic_factory(mode))
                revisions=0; count=1; status='DRAFT_WITH_POSTHOC_DIAGNOSTIC_CRITIC'
            stage=mode+'_INTEGRITY'
            if (evidence_digest(evidence_copy)!=initial or evidence_digest(frozen_evidence)!=initial
                    or evidence_digest(evidence)!=initial or plan_copy!=frozen_plan):
                raise ArchitectureEvalError('FROZEN_INPUT_MUTATED')
            if financial_sha is None:
                financial_sha=financial_digest(draft['draft_markdown'])
            record=_summarize_arm(mode,draft,review,revisions=revisions,status=status,
                                  elapsed_ms=(perf_counter()-t0)*1000,before_sha=initial,
                                  finance_sha=financial_sha,version_count=count)
            if usage_before is not None:
                usage_after=measurement_probe()
                record['downstream_model_calls_including_posthoc_audit']=(
                    usage_after['downstream_llm_requests']-usage_before['downstream_llm_requests'])
                record['prompt_tokens_observed']=(usage_after['prompt_tokens_observed']-usage_before['prompt_tokens_observed'])
                record['completion_tokens_observed']=(usage_after['completion_tokens_observed']-usage_before['completion_tokens_observed'])
                record['model_responses_missing_usage']=(usage_after['responses_without_usage']-usage_before['responses_without_usage'])
                record['cost_usd']=None
            results.append(record)
            if capture_review_materials:
                # Raw drafts are local reviewer inputs, never a model-quality metric.
                # Capture only after all approval, citation, and financial guards pass.
                review_materials.append({
                    'configuration': mode,
                    'draft_sha256': record['final_draft_sha256'],
                    'draft_markdown': draft['draft_markdown'],
                    'critic_findings': [{
                        'claim_id': f['claim_id'], 'verdict': f['verdict'],
                        'citations': list(f.get('citations', []))
                    } for f in review['findings']],
                    'human_report_approved': False,
                    'publication_performed': False,
                })
        except Exception as exc:
            raise _stage_error(stage, exc) from None
    if len({x['input_evidence_sha256'] for x in results})!=1 or len({x['financial_section_sha256'] for x in results})!=1:
        raise ArchitectureEvalError('ARMS_NOT_PAIRED')
    receipt={'phase':'PHASE8C_DOWNSTREAM_ARCHITECTURE_PILOT', 'status':'PASS_PAIRED_PILOT',
            'pilot_scope':'SINGLE_APPROVED_MSFT_GOOGL_RESEARCH_PACKET',
            'configurations':list(CONFIGS),'input_evidence_sha256':initial,
            'financial_section_sha256':financial_sha,
            'results':results, 'human_approval_performed':False,'portal_publication_performed':False,
            'heldout_quality_measured':False,
            'limitations':[
                'C0/C1/C2 isolate Stage 4C downstream report architecture; shared upstream synthesis is not a zero-LLM research baseline',
                'C0/C1 have posthoc diagnostic Critic calls, not revisions; these calls consume evaluation resources',
                'C2 has a larger allowed inference budget; latency and cost are a quality-resource tradeoff, not equal-budget causal estimates',
                'Critic verdicts are model opinions and NOT independently adjudicated correctness or citation entailment',
                'One approved task is a pilot, not 40 held-out tasks or a statistical efficacy claim',
                'GOOGL revenue tag blocker persists: no approval or portal publication',
            ]}
    if capture_review_materials:
        receipt['review_materials'] = review_materials
        receipt['untrusted_draft_materials_present'] = True
    return receipt


class MeteredChatClient:
    """Synchronous OpenAI-compatible wrapper recording observed downstream requests only.

    Enforces a hard *request* cap, counts tokens when provider returns usage.
    No raw prompts, outputs, API keys or customer data are recorded.
    """
    def __init__(self, inner, max_calls:int):
        if type(max_calls) is not int or not 1 <= max_calls <= 40:
            raise ArchitectureEvalError('INVALID_MODEL_CALL_LIMIT')
        self.inner=inner; self.max_calls=max_calls; self.calls=0
        self.usage_prompt=0; self.usage_completion=0; self.usage_missing=0
        self.elapsed_ms=0.
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self._create))
    def _create(self, **kwargs):
        if self.calls >= self.max_calls:
            raise ArchitectureEvalError('DOWNSTREAM_MODEL_CALL_LIMIT_EXCEEDED')
        self.calls+=1; started=perf_counter()
        try: response=self.inner.chat.completions.create(**kwargs)
        finally: self.elapsed_ms += (perf_counter()-started)*1000
        usage=getattr(response,'usage',None)
        p=getattr(usage,'prompt_tokens',None); c=getattr(usage,'completion_tokens',None)
        if (type(p) is int and p>=0) and (type(c) is int and c>=0):
            self.usage_prompt+=p;self.usage_completion+=c
        else:self.usage_missing+=1
        return response
    def snapshot(self):
        return {'downstream_llm_requests':self.calls, 'prompt_tokens_observed':self.usage_prompt,
                'completion_tokens_observed':self.usage_completion,
                'responses_without_usage':self.usage_missing,
                'downstream_llm_elapsed_ms':round(self.elapsed_ms,3),
                'usd_cost':None,'usd_cost_measured':False}


async def synthetic_smoke(root:Path) -> dict:
    """Run actual Stage 4C functions with deterministic fixtures, zero outside calls."""
    from .phase7d_evaluation import (ScriptedWriterClient, SyntheticCanonicalMCP,
                                      _load_fixed_fixture, scripted_critic, scripted_rewriter)
    from .stage4c1_writer import OpenRouterReportWriter
    plan,evidence=_load_fixed_fixture(root)
    n=0
    def writer_factory(mode):
        nonlocal n
        n+=1
        return OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
            client=ScriptedWriterClient('neutral'), editorial_lessons=[])
    outcome=await paired_downstream_evaluation(plan,evidence,thread_id='b3a5fcf8dbdb430ba814727b7c0dab14',
        allowed=('MSFT','GOOGL'),budget=80000,call=SyntheticCanonicalMCP(),
        writer_factory=writer_factory, critic_factory=lambda mode:scripted_critic,
        rewriter_factory=lambda mode:scripted_rewriter,max_revisions=2)
    if n!=2:
        raise ArchitectureEvalError('SYNTHETIC_WRITER_CALL_COUNT_INVALID')
    outcome.update({'status':'PASS_SYNTHETIC_WIRING_ONLY','experiment_kind':'DETERMINISTIC_SCRIPTED_TEST',
                    'real_llm_calls':0,'real_mcp_calls':0,'real_sec_sources_used':False,
                    'real_portal_operations':0,'real_quality_improvement_measured':False})
    return outcome


async def real_approved_pilot(root:Path, thread_id:str, *, max_client_calls:int=20,
                              max_revisions:int=2, upstream_mode:str='synthesized',
                              capture_review_materials:bool=False) -> dict:
    """Explicit opt-in LIVE pilot. Reuses same Stage 4B3 SEC packet across arms."""
    from openai import OpenAI
    from .stage4a_config import load_planner_settings, require_openrouter_key
    from .stage4b_cli import MCPResearchGateway, approved_plan_from_stage4a
    from .stage4b3_cli import run as build_b3_evidence
    from .stage4c1_writer import OpenRouterReportWriter
    from .stage4c2_critic import OpenRouterComplianceCritic
    from .stage4c3_revision import OpenRouterTargetedRewriter

    if upstream_mode not in UPSTREAM_MODES or not isinstance(upstream_mode, str):
        raise ArchitectureEvalError('UPSTREAM_MODE_INVALID')
    settings=load_planner_settings(root)
    plan=approved_plan_from_stage4a(root,thread_id)
    if sorted(plan['companies'])!=['GOOGL','MSFT']:
        raise ArchitectureEvalError('ONLY_APPROVED_MSFT_GOOGL_PILOT_SUPPORTED')
    source_start=perf_counter()
    # Explicitly select one of two *real* Stage 4B3 read-only paths.
    # The audited path is a supported evidence-only contract, never an automatic fallback.
    # Both are validated by Stage 4C and shared unchanged across C0/C1/C2.
    uses_upstream_model = upstream_mode == 'synthesized'
    try:
        evidence=await build_b3_evidence(root,thread_id,no_llm=not uses_upstream_model)
    except Exception as exc:
        raise _stage_error('B3_SHARED_UPSTREAM', exc) from None
    upstream_ms=round((perf_counter()-source_start)*1000,3)
    required_phase = ('STAGE4B_GROUNDED_SYNTHESIS_READY' if uses_upstream_model
                      else 'STAGE4B_SUPERVISOR_EVIDENCE_READY')
    if (evidence.get('phase') != required_phase or
            evidence.get('llm_synthesis_performed') is not uses_upstream_model or
            (not uses_upstream_model and evidence.get('synthesis') is not None)):
        raise ArchitectureEvalError('SHARED_UPSTREAM_MODE_CONTRACT_MISMATCH')
    if (evidence.get('semantic_entailment_checked') is not False or
            evidence.get('publication_performed') is not False):
        raise ArchitectureEvalError('UPSTREAM_PROVENANCE_OR_PUBLICATION_INVALID')
    base=OpenAI(api_key=require_openrouter_key(root),base_url=settings.base_url,
                timeout=settings.timeout_seconds,max_retries=1)
    try:
        meter=MeteredChatClient(base,max_calls=max_client_calls)
        writer=lambda mode:OpenRouterReportWriter(settings,client=meter,editorial_lessons=[])
        critic=lambda mode:OpenRouterComplianceCritic(settings,client=meter)
        rewriter=lambda mode:OpenRouterTargetedRewriter(settings,client=meter)
        try:
            async with MCPResearchGateway(root) as gateway:
                receipt=await paired_downstream_evaluation(plan,evidence,thread_id=thread_id,
                    allowed=settings.allowed_tickers,budget=settings.token_budget,call=gateway,
                    writer_factory=writer,critic_factory=critic,rewriter_factory=rewriter,
                    max_revisions=max_revisions,measurement_probe=meter.snapshot,
                    capture_review_materials=capture_review_materials)
        except ArchitectureEvalError:
            raise
        except Exception as exc:
            raise _stage_error('DOWNSTREAM_MCP_SETUP', exc) from None
        receipt.update({'experiment_kind':('LIVE_APPROVED_PLAN_REAL_SEC_AND_LLM' if uses_upstream_model
                                           else 'LIVE_APPROVED_PLAN_AUDITED_SEC_DOWNSTREAM_LLM'),
                        'shared_upstream_mode':upstream_mode,
                        'real_sec_sources_used':True,'shared_upstream_model_used':uses_upstream_model,
                        'shared_upstream_llm_requests_observed':(None if uses_upstream_model else 0),
                        'shared_upstream_wall_latency_ms':upstream_ms,
                        'shared_upstream_llm_requests_measured':False,
                        'downstream_usage':meter.snapshot(),
                        'model_identifier':settings.model,
                        'temperature_control_verified':False,
                        'real_quality_improvement_measured':False,
                        'publication_performed':False})
        return receipt
    finally:
        base.close()


def preflight_live(root:Path, thread_id:str, *, upstream_mode:str='synthesized') -> dict:
    """Read-only checks before paid 8C run; no model/MCP invocations."""
    from .stage4a_config import load_planner_settings, require_openrouter_key
    from .stage4b_cli import approved_plan_from_stage4a
    if upstream_mode not in UPSTREAM_MODES or not isinstance(upstream_mode, str):
        raise ArchitectureEvalError('UPSTREAM_MODE_INVALID')
    root=Path(root).resolve()
    settings=load_planner_settings(root)
    plan=approved_plan_from_stage4a(root,thread_id)
    if sorted(plan.get('companies',[]))!=['GOOGL','MSFT']:
        raise ArchitectureEvalError('ONLY_APPROVED_MSFT_GOOGL_PILOT_SUPPORTED')
    for rel in ('data/parsed/10k_passages.jsonl','data/retrieval_index/search_records.json',
                'data/retrieval_index/embeddings.npz','data/checkpoints/stage4a.sqlite3'):
        path=root/rel
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ArchitectureEvalError('PREFLIGHT_REQUIRED_LOCAL_INPUT_MISSING')
    # A key is needed for live mode; never print or persist its value.
    require_openrouter_key(root)
    return {'phase':'PHASE8C_ARCHITECTURE_PREFLIGHT','status':'READY_FOR_EXPLICIT_LIVE_PILOT',
            'shared_upstream_mode':upstream_mode, 'upstream_llm_expected':upstream_mode=='synthesized',
            'company_scope':sorted(plan['companies']),
            'shared_approved_plan':'PERSISTED_STAGE4A_HUMAN_APPROVED',
            'model_identifier':settings.model,
            'read_only':True,'model_calls_performed':0,'mcp_calls_performed':0,
            'portal_publication_performed':False,'estimated_usd_cost':None,
            'note':'Live downstream calls limited by --max-client-calls; shared upstream B3 model call is not metered by this guard'}

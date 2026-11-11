"""Phase 7D: paired Reflexion evaluation with a deliberately scripted model oracle.

This is a reproducible *integration/causal wiring* experiment, NOT empirical
LLM quality measurement. Both conditions use the same real Stage 4C Writer,
Critic, bounded revision loop, risk packet, and fake canonical get_passage.
The response rule is intentionally controlled. No network, real SEC content,
portal, signature, or persistent lesson database is used.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .phase7a_reflexion import GUIDANCE
from .phase7b_reflexion import validate_editorial_advice
from .stage4c1_writer import OpenRouterReportWriter, validate_writer_input
from .stage4c3_revision import run_revision_loop, run_revision_graph

FIXTURE_SHA256 = 'bc64dfc404bbdf152b671cf3a5015275829259f0ae3990e028604f4994a3b139'
THREAD_ID = 'b3a5fcf8dbdb430ba814727b7c0dab14'
CASES = ('responsive', 'neutral', 'resistant')
GOOD_SUMMARY = (
    'Microsoft and Alphabet describe cybersecurity and data-handling exposure in selected filing passages. '
    'These disclosures offer limited context for comparison, and the implications require independent source-level review.'
)
OVERCLAIM_SUMMARY = (
    'Microsoft and Alphabet face inevitable cybersecurity collapse, as their filings clearly prove that '
    'business disruption will necessarily follow for both companies without exception.'
)


class ExperimentError(ValueError):
    pass


def _load_fixed_fixture(root: Path) -> tuple[dict, dict]:
    root = Path(root).resolve()
    source = root / 'security' / 'phase7d_synthetic_case.json'
    if (source.is_symlink() or not source.is_file() or source.stat().st_size > 30_000
            or not source.resolve().is_relative_to(root)):
        raise ExperimentError('FIXTURE_MISSING_OR_UNSAFE')
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ExperimentError('FIXTURE_INTEGRITY_MISMATCH')
    try:
        packet = json.loads(raw)
    except ValueError as exc:
        raise ExperimentError('INVALID_FIXTURE') from exc
    if (packet.get('fixture_id') != 'SYNTHETIC_PHASE7D_MSFT_GOOGL'
            or packet.get('provenance') != 'SYNTHETIC_TEST_FIXTURE_NOT_REAL_SEC_DATA'
            or packet.get('thread_id') != THREAD_ID):
        raise ExperimentError('UNTRUSTED_FIXTURE_ID')
    plan, evidence = packet['plan'], packet['evidence']
    if plan.get('companies') != ['MSFT', 'GOOGL'] or evidence.get('source_thread_id') != THREAD_ID:
        raise ExperimentError('FIXTURE_SCOPE_MISMATCH')
    validate_writer_input(plan, evidence, thread_id=THREAD_ID, allowed=('MSFT', 'GOOGL'), budget=80000)
    return plan, evidence


class ScriptedWriterClient:
    """Produces deterministic, pre-scripted summaries based on exact advice presence.

    It is not a hosted LLM. `responsive` intentionally responds to a reminder;
    `neutral` and `resistant` intentionally ignore it.
    """
    def __init__(self, case: str):
        if case not in CASES:
            raise ExperimentError('INVALID_CASE')
        self.case = case
        self.calls = 0
        self.has_reminder = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict]) -> Any:
        if model != 'phase7d-scripted-model' or len(messages) < 2:
            raise ExperimentError('INVALID_MODEL_REQUEST')
        self.calls += 1
        payload = json.loads(messages[1]['content'])
        lessons = payload.get('editorial_quality_reminders', [])
        validate_editorial_advice(lessons)
        self.has_reminder = bool(lessons)
        citations = payload['comparison_texts'][0]['citations']
        if (not isinstance(citations, list) or len(citations) < 2):
            raise ExperimentError('INVALID_CITATIONS')
        use_good = self.case == 'neutral' or (self.case == 'responsive' and self.has_reminder)
        summary = GOOD_SUMMARY if use_good else OVERCLAIM_SUMMARY
        answer = json.dumps({'executive_summary': summary, 'citations': citations})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


class SyntheticCanonicalMCP:
    """No real MCP dispatcher/network is imported or invoked."""
    def __init__(self):
        self.calls = 0

    async def __call__(self, role: str, tool: str, args: dict) -> dict:
        if role != 'compliance_critic' or tool != 'get_passage' or set(args) != {'passage_id'}:
            raise ExperimentError('UNAUTHORIZED_TOOL')
        pid = args['passage_id']
        try:
            ticker, date, item, sequence = pid.split('_')
        except ValueError as exc:
            raise ExperimentError('INVALID_SOURCE_ID') from exc
        if ticker not in ('MSFT', 'GOOGL') or item != 'Item1A' or not sequence.isdigit():
            raise ExperimentError('INVALID_SOURCE_ID')
        self.calls += 1
        return {'ok': True, 'data': {
            'passage_id': pid, 'ticker': ticker, 'report_date': date, 'item': '1A',
            'source_url': 'https://www.sec.gov/Archives/synthetic/phase7d_test.htm',
            'source_sha256': 'a' * 64, 'untrusted_source_text': True,
            'text': ('Synthetic SEC-style fixture: the registrant identifies cybersecurity risks, '
                     'privacy exposures and possible operational disruption. This text is not real SEC evidence.')
        }}


def scripted_critic(claim_id: str, text: str, citations: list[str], source_packet: dict) -> dict:
    # A pre-declared rule, not a semantic entailment judge.
    verdict = 'UNSUPPORTED' if claim_id == 'executive_summary' and 'inevitable cybersecurity collapse' in text else 'SUPPORTED'
    return {'claim_id': claim_id, 'verdict': verdict,
            'reason': ('The scripted oracle flags the deliberately exaggerated summary'
                       if verdict == 'UNSUPPORTED' else
                       'The scripted oracle classifies this fixture claim as supported'),
            'citations': citations}


def scripted_rewriter(*, claim_id: str, previous_text: str, allowed_citations: list[str], **kwargs) -> dict:
    if claim_id != 'executive_summary' or previous_text != OVERCLAIM_SUMMARY:
        raise ExperimentError('UNEXPECTED_REVISION_TARGET')
    return {'text': GOOD_SUMMARY, 'citations': allowed_citations}


def _advice(enabled: bool) -> list[dict]:
    if not enabled:
        return []
    code, guidance = GUIDANCE['UNSUPPORTED']
    return validate_editorial_advice([{'claim_id': 'executive_summary', 'lesson_code': code,
                                      'guidance': guidance}])


def _source_fingerprint(evidence: dict) -> str:
    canonical = {key: evidence[key] for key in ('financial_comparability',
                 'risk_evidence_citations', 'warnings', 'citation_count', 'xbrl_fact_count')}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _verdict_counts(review: dict) -> dict[str, int]:
    return {v: sum(f['verdict'] == v for f in review['findings'])
            for v in ('SUPPORTED', 'UNSUPPORTED', 'UNCERTAIN', 'NOT_REVIEWED')}


async def run_condition(root: Path, *, case: str, enabled: bool, engine: str = 'loop') -> dict:
    if case not in CASES or type(enabled) is not bool or engine not in ('loop', 'graph'):
        raise ExperimentError('INVALID_EXPERIMENT_ARGUMENT')
    plan, evidence = _load_fixed_fixture(root)
    pre_hash = _source_fingerprint(evidence)
    client = ScriptedWriterClient(case)
    writer = OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
                                    client=client, editorial_lessons=_advice(enabled))
    mcp = SyntheticCanonicalMCP()
    runner = run_revision_loop if engine == 'loop' else run_revision_graph
    result = await runner(deepcopy(plan), deepcopy(evidence), thread_id=THREAD_ID,
                          allowed=('MSFT', 'GOOGL'), budget=80000, call=mcp,
                          writer=writer, critic=scripted_critic, rewriter=scripted_rewriter,
                          max_revisions=2)
    if (not result['versions'] or result['revision_count'] > 2
            or result['human_report_approved'] is not False
            or result['publication_performed'] is not False
            or result['report_submitted_for_review'] is not False
            or 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN' not in result['hard_blockers']):
        raise ExperimentError('WORKFLOW_INVARIANT_FAILED')
    if _source_fingerprint(evidence) != pre_hash:
        raise ExperimentError('SOURCE_EVIDENCE_MUTATED')
    for version in result['versions']:
        d = version['draft']
        if (d['human_report_approved'] is not False or d['publication_performed'] is not False or
                'GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED' not in d['draft_markdown']):
            raise ExperimentError('DRAFT_INVARIANT_FAILED')
    first, final = result['versions'][0]['review'], result['versions'][-1]['review']
    # Compare the exact rendered financial section, not just a reported fixture checksum.
    draft_text = result['versions'][0]['draft']['draft_markdown']
    try:
        financial_section = draft_text.split('## Financial findings\n', 1)[1].split('\n## Risk evidence', 1)[0]
    except IndexError as exc:
        raise ExperimentError('FINANCIAL_SECTION_NOT_FOUND') from exc
    financial_section_sha = hashlib.sha256(financial_section.encode('utf-8')).hexdigest()
    return {'case': case, 'reflexion': 'ON' if enabled else 'OFF',
            'initial_verdicts': _verdict_counts(first), 'final_verdicts': _verdict_counts(final),
            'revisions': result['revision_count'], 'versions': len(result['versions']),
            'writer_stub_calls': client.calls, 'synthetic_passage_reads': mcp.calls,
            'editorial_reminder_present': client.has_reminder,
            'source_fingerprint': pre_hash,
            'rendered_financial_section_sha256': financial_section_sha,
            'publication_performed': False,
            'human_report_approved': False,
            'existing_reconciliation_blocker_preserved': True}


async def evaluate(root: Path, *, engine: str = 'loop') -> dict:
    if engine not in ('loop', 'graph'):
        raise ExperimentError('INVALID_ENGINE')
    results = []
    for case in CASES:
        for enabled in (False, True):
            results.append(await run_condition(root, case=case, enabled=enabled, engine=engine))
    paired = []
    for index, case in enumerate(CASES):
        off, on = results[index*2:index*2+2]
        if (off['source_fingerprint'] != on['source_fingerprint']
                or off['rendered_financial_section_sha256'] != on['rendered_financial_section_sha256']
                or off['existing_reconciliation_blocker_preserved'] is not True
                or on['existing_reconciliation_blocker_preserved'] is not True):
            raise ExperimentError('ARMS_NOT_COMPARABLE')
        paired.append({'case': case,
                       'initial_unsupported_off': off['initial_verdicts']['UNSUPPORTED'],
                       'initial_unsupported_on': on['initial_verdicts']['UNSUPPORTED'],
                       'revisions_off': off['revisions'], 'revisions_on': on['revisions'],
                       'delta_initial_unsupported_on_minus_off': (on['initial_verdicts']['UNSUPPORTED'] -
                                                                   off['initial_verdicts']['UNSUPPORTED']),
                       'delta_revisions_on_minus_off': on['revisions'] - off['revisions']})
    return {'status': 'PASS', 'phase': 'PHASE7D_REFLEXION_PAIRED_EVALUATION',
            'mode': 'CONTROLLED_SCRIPTED_MODEL_AND_CRITIC_ORACLE',
            'engine': engine, 'fixture_sha256': FIXTURE_SHA256,
            'synthetic_test_only': True, 'real_llm_invocations': 0, 'real_mcp_invocations': 0,
            'real_sec_sources_used': False, 'real_reflexion_store_modified': False,
            'real_portal_operations': 0, 'publication_performed': False,
            'company_scope': ['GOOGL', 'MSFT'], 'trial_count': len(results),
            'case_count': len(CASES), 'paired_results': paired,
            'aggregate': {
                'initial_unsupported_off': sum(x['initial_unsupported_off'] for x in paired),
                'initial_unsupported_on': sum(x['initial_unsupported_on'] for x in paired),
                'revisions_off': sum(x['revisions_off'] for x in paired),
                'revisions_on': sum(x['revisions_on'] for x in paired),
            },
            'limitations': [
                'Scripted writer/critic behavior is predefined; improvements are demonstration outcomes, not measured LLM efficacy',
                'Source packet is a synthetic fixture; no live SEC truth or semantic entailment was assessed',
                'No real lesson was present in the earlier production store; ON uses a validated static editorial fixture',
                'No statistical significance, real latency/cost, or out-of-sample generalization claim',
                'GOOGL revenue-concept blocker is preserved and the report cannot be published',
            ]}

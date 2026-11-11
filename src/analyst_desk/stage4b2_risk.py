"""Stage 4B-2 — evidence-limited, read-only cross-company risk comparison.

Searches the *latest ingested* Item 1A filing per company, re-reads complete
canonical passages over MCP, verifies the lookup provenance, and builds a
retrieval-supported thematic matrix. This is NOT an LLM assertion that a risk
is absent from the filing, nor a historical Item 1A diff.
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Any, TypedDict

from .stage4a_permissions import assert_tool_permission
from .stage4b_research import ResearchError, ToolCaller, _hits, _tool_data, check_approved_plan

# Curated, versioned risk taxonomy; matches are lexical *indicators*, not
# legal materiality assessments and never negative evidence about a filing.
THEMES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('cyber_privacy', 'cybersecurity data breaches cyber attacks information security privacy personal data',
     ('cybersecurity', 'cyberattack', 'cyber attack', 'security incident', 'data breach', 'data privacy', 'data protection', 'user data', 'information security')),
    ('ai_ip', 'artificial intelligence generative AI automated systems intellectual property copyright infringement risk',
     ('artificial intelligence', 'ai-enabled', 'generative ai', 'ai systems', 'ai products', 'intellectual property', 'copyright', 'infringement')),
    ('competition_regulation', 'antitrust competition law digital market regulation regulatory scrutiny litigation',
     ('antitrust', 'competition law', 'competition regulation', 'digital market', 'anti-competitive', 'anticompetitive', 'regulatory scrutiny')),
    ('service_infrastructure', 'cloud outage reliability critical infrastructure data center disruption power supply',
     ('service outage', 'service interruption', 'service disruption', 'critical infrastructure', 'data center', 'datacenter', 'cloud infrastructure', 'power supply')),
)

THEME_IDS = tuple(t[0] for t in THEMES)
_SEC_ARCHIVE = 'https://www.sec.gov/Archives/'
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_PAS_ID = re.compile(r'[A-Za-z0-9_.\-]{8,160}\Z')


class RiskState(TypedDict, total=False):
    plan: dict[str, Any]
    approved: bool
    research_results: list[dict[str, Any]]
    theme_id: str
    theme_results: Annotated[list[dict[str, Any]], operator.add]
    status: str
    matrix: dict[str, Any]


def _verify_baseline(plan: dict, baseline: list[dict]) -> dict[str, dict]:
    if not isinstance(baseline, list) or len(baseline) != len(plan['companies']):
        raise ResearchError('Missing or duplicate company research baseline')
    mapped: dict[str, dict] = {}
    for result in baseline:
        if not isinstance(result, dict):
            raise ResearchError('Invalid company research baseline')
        ticker = result.get('ticker')
        if ticker not in plan['companies'] or ticker in mapped:
            raise ResearchError('Research baseline company is not uniquely approved')
        date = result.get('report_date')
        if not isinstance(date, str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) is None:
            raise ResearchError('Research baseline has invalid filing period')
        if not isinstance(result.get('filings'), list) or not result['filings'] or result['filings'][0].get('report_date') != date:
            raise ResearchError('Research baseline lacks a matching latest SEC filing')
        mapped[ticker] = result
    return mapped


def _terms_in(text: str, terms: tuple[str, ...]) -> list[str]:
    lower = text.casefold()
    return [term for term in terms if re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', lower)]


def _excerpt(text: str, term: str, length: int = 300) -> str:
    """Literal fragment around first matched evidence indicator (no generated text)."""
    match = re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', text, re.I)
    if match is None:
        return ''
    start = max(0, match.start() - 90)
    end = min(len(text), start + length)
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


def _validate_full_passage(data: dict, hit: dict, ticker: str, date: str) -> str:
    """Cross-check full canonical text against the searched source envelope."""
    for key, expected in (('ticker', ticker), ('report_date', date), ('item', '1A'),
                          ('passage_id', hit['passage_id']), ('source_sha256', hit['source_sha256']),
                          ('source_url', hit['source_url'])):
        if data.get(key) != expected:
            raise ResearchError('Canonical passage provenance mismatch: ' + key)
    if data.get('untrusted_source_text') is not True:
        raise ResearchError('Full passage missing untrusted text designation')
    if data.get('source_url', '').startswith(_SEC_ARCHIVE) is not True or _SHA.fullmatch(data['source_sha256']) is None:
        raise ResearchError('Canonical passage source fails SEC provenance check')
    if _PAS_ID.fullmatch(data['passage_id']) is None:
        raise ResearchError('Canonical passage ID is invalid')
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 500_000:
        raise ResearchError('Invalid canonical passage text')
    return text


async def compare_theme(theme_id: str, plan: dict, baseline: list[dict], call: ToolCaller) -> dict[str, Any]:
    """Search + inspect full source text for each approved company and risk theme."""
    if theme_id not in THEME_IDS:
        raise ResearchError('Unknown risk taxonomy ID')
    mapped = _verify_baseline(plan, baseline)
    _, query, terms = next(t for t in THEMES if t[0] == theme_id)
    company_data: dict[str, Any] = {}
    for ticker in plan['companies']:
        date = mapped[ticker]['report_date']
        assert_tool_permission('risk_diff', 'search_passages')
        search = _tool_data(await call('risk_diff', 'search_passages', {
            'ticker': ticker, 'item': '1A', 'report_date': date,
            'query': query, 'top_n': 5, 'rerank': True}), 'search_passages')
        hits = _hits(search, ticker, '1A', report_date=date, limit=5)
        matches = []
        seen: set[str] = set()
        for hit in hits:
            if hit['passage_id'] in seen:
                continue
            seen.add(hit['passage_id'])
            assert_tool_permission('risk_diff', 'get_passage')
            full = _tool_data(await call('risk_diff', 'get_passage', {'passage_id': hit['passage_id']}), 'get_passage')
            body = _validate_full_passage(full, hit, ticker, date)
            matched = _terms_in(body, terms)
            if matched:
                matches.append({
                    'passage_id': hit['passage_id'], 'ticker': ticker, 'report_date': date,
                    'source_url': hit['source_url'], 'source_sha256': hit['source_sha256'],
                    'matched_terms': matched, 'source_excerpt': _excerpt(body, matched[0]),
                    'untrusted_source_text': True,
                })
            if len(matches) >= 2:
                break
        company_data[ticker] = {'retrieved_hit_count': len(hits), 'matched_passages': matches,
                                'matched_evidence_found': bool(matches)}
    evidence_companies = [t for t in plan['companies'] if company_data[t]['matched_evidence_found']]
    label = 'MATCHED_EVIDENCE_BOTH' if len(evidence_companies) == len(plan['companies']) else (
        'MATCHED_EVIDENCE_SOME' if evidence_companies else 'NO_MATCH_IN_RETRIEVED_PASSAGES')
    return {'theme': theme_id, 'comparison_label': label, 'companies': company_data,
            'interpretation_limit': 'A missing lexical match in retrieved passages is NOT evidence a risk is absent from a filing',
            'historical_comparison_performed': False}


def build_risk_graph(*, call: ToolCaller, allowed: tuple[str, ...], budget: int):
    """LangGraph themed parallel fan-out; approved plan and Stage 4B-1 inputs required."""
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Send

    def gate(state: RiskState) -> dict:
        plan = check_approved_plan(state.get('plan'), approved=state.get('approved', False), allowed=allowed, budget=budget)
        _verify_baseline(plan, state.get('research_results'))
        return {'plan': plan, 'status': 'RISK_FANOUT_APPROVED'}

    def dispatch(state: RiskState):
        return [Send('analyze_theme', {'theme_id': theme_id, 'plan': state['plan'],
                                       'research_results': state['research_results']}) for theme_id in THEME_IDS]

    async def theme_node(state: RiskState) -> dict:
        result = await compare_theme(state['theme_id'], state['plan'], state['research_results'], call)
        return {'theme_results': [result]}

    def merge(state: RiskState) -> dict:
        entries = state.get('theme_results', [])
        if len(entries) != len(THEME_IDS) or {v.get('theme') for v in entries} != set(THEME_IDS):
            raise ResearchError('Risk graph missing or duplicated theme results')
        result_by_theme = {v['theme']: v for v in entries}
        all_citations = sorted({p['passage_id'] for entry in entries
                                for company in entry['companies'].values()
                                for p in company['matched_passages']})
        return {'status': 'RISK_EVIDENCE_MATRIX_READY', 'matrix': {
            'themes': [result_by_theme[tid] for tid in THEME_IDS],
            'cited_passage_ids': all_citations, 'historical_item1a_diff_performed': False,
            'LLM_synthesis_performed': False, 'report_published': False,
            'scope': 'Current latest ingested Item 1A, source-verified lexical evidence indicators only',
            'warnings': ['SEARCH_COVERAGE_LIMITED_TO_TOP_5_PER_THEME_AND_COMPANY',
                         'NO_ABSENCE_CLAIMS_FROM_RETRIEVAL_RESULTS',
                         'CROSS_COMPANY_FISCAL_PERIODS_NOT_IDENTICAL',
                         'HISTORICAL_ITEM1A_NOT_YET_INGESTED'],
        }}

    builder = StateGraph(RiskState)
    builder.add_node('approved_plan_gate', gate)
    builder.add_node('analyze_theme', theme_node)
    builder.add_node('consolidate_risk_matrix', merge)
    builder.add_edge(START, 'approved_plan_gate')
    builder.add_conditional_edges('approved_plan_gate', dispatch, ['analyze_theme'])
    builder.add_edge('analyze_theme', 'consolidate_risk_matrix')
    builder.add_edge('consolidate_risk_matrix', END)
    return builder.compile()

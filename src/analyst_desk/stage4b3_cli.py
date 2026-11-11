"""Stage 4B-3: re-run B-1 and B-2 with real MCP, audit and optionally synthesize."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT, load_planner_settings
from .stage4b_cli import MCPResearchGateway, approved_plan_from_stage4a
from .stage4b_research import ResearchError, build_research_graph
from .stage4b2_risk import build_risk_graph
from .stage4b3_supervisor import OpenRouterRiskSynthesizer, build_supervisor_graph


async def run(root: Path, thread_id: str, *, no_llm: bool = False) -> dict:
    # Approval is read from durable Stage 4A SQLite, NOT trusted from arguments.
    plan = approved_plan_from_stage4a(root, thread_id)
    settings = load_planner_settings(root)
    async with MCPResearchGateway(root) as gateway:
        research_graph = build_research_graph(call=gateway, allowed=settings.allowed_tickers, budget=settings.token_budget)
        research = await research_graph.ainvoke({'plan': plan, 'approved': True, 'research_results': []})
        if research.get('status') != 'RESEARCH_EVIDENCE_READY':
            raise ResearchError('Stage 4B-1 research is incomplete')
        risk_graph = build_risk_graph(call=gateway, allowed=settings.allowed_tickers, budget=settings.token_budget)
        risk = await risk_graph.ainvoke({'plan': plan, 'approved': True,
                                        'research_results': research['research_results'], 'theme_results': []})
        if risk.get('status') != 'RISK_EVIDENCE_MATRIX_READY':
            raise ResearchError('Stage 4B-2 risk matrix is incomplete')
    synthesizer = None if no_llm else OpenRouterRiskSynthesizer(settings, root=root)
    supervisor = build_supervisor_graph(allowed=settings.allowed_tickers, budget=settings.token_budget,
                                        synthesizer=synthesizer)
    final = await supervisor.ainvoke({'plan': plan, 'approved': True,
                                      'research_results': research['research_results'],
                                      'risk_matrix': risk['matrix']})
    expected = 'SUPERVISOR_EVIDENCE_READY' if no_llm else 'GROUNDED_SYNTHESIS_READY'
    if final.get('status') != expected:
        raise ResearchError('Stage 4B-3 supervisor did not complete')
    packet = final['audited']
    return {'status': 'PASS',
            'phase': 'STAGE4B_SUPERVISOR_EVIDENCE_READY' if no_llm else 'STAGE4B_GROUNDED_SYNTHESIS_READY',
            'source_thread_id': thread_id, 'approved_plan_consumed': True,
            'transport': 'FastMCP in-memory + LangGraph orchestration',
            'llm_synthesis_performed': not no_llm,
            'model': None if no_llm else settings.model,
            'financial_comparability': packet['financial_comparability'],
            'risk_evidence_citations': {theme: {ticker: [e['passage_id'] for e in entries]
                                       for ticker, entries in companies.items()}
                                      for theme, companies in packet['risk_evidence'].items()},
            'citation_count': len(packet['citations']), 'xbrl_fact_count': len(packet['xbrl_fact_ids']),
            'warnings': packet['warnings'],
            'synthesis': final.get('synthesized') if not no_llm else None,
            'semantic_entailment_checked': False,
            'historical_item1a_diff_performed': False, 'analytical_draft_generated': False,
            'publication_performed': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Read-only Stage 4B-3 supervisor and audited synthesis')
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--no-llm', action='store_true', help='Only the deterministic evidence audit; no API cost')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(run(args.project_root.resolve(), args.thread_id, no_llm=args.no_llm)),
                         indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Never include server exception chains, model raw content, prompts or API credentials.
        safe = str(exc) if isinstance(exc, ResearchError) else 'See private diagnostics; credentials are not logged'
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__, 'message': safe}))
        return 2


if __name__ == '__main__':
    sys.exit(main())

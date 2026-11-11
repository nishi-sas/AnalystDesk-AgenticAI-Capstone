"""Stage 4B-2 — approved plan -> parallel MCP company research -> risk matrix."""
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


async def run(root: Path, thread_id: str) -> dict:
    plan = approved_plan_from_stage4a(root, thread_id)
    settings = load_planner_settings(root)
    async with MCPResearchGateway(root) as gateway:
        research_graph = build_research_graph(call=gateway, allowed=settings.allowed_tickers, budget=settings.token_budget)
        research = await research_graph.ainvoke({'plan': plan, 'approved': True, 'research_results': []})
        if research.get('status') != 'RESEARCH_EVIDENCE_READY':
            raise ResearchError('Stage 4B-1 evidence is not ready')
        risk_graph = build_risk_graph(call=gateway, allowed=settings.allowed_tickers, budget=settings.token_budget)
        risk = await risk_graph.ainvoke({'plan': plan, 'approved': True, 'research_results': research['research_results'],
                                        'theme_results': []})
    if risk.get('status') != 'RISK_EVIDENCE_MATRIX_READY':
        raise ResearchError('Stage 4B-2 risk evidence is not ready')
    return {'status': 'PASS', 'phase': 'STAGE4B_RISK_EVIDENCE_MATRIX_READY',
            'source_thread_id': thread_id, 'approved_plan_consumed': True,
            'transport': 'FastMCP in-memory protocol',
            'orchestration': 'LangGraph company Send fan-out + risk theme Send fan-out',
            'research_summary': research['summary'], 'risk_matrix': risk['matrix'],
            'publication_performed': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Build source-limited Item 1A risk comparison from an approved plan')
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(run(args.project_root.resolve(), args.thread_id)), indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        msg = str(exc) if isinstance(exc, ResearchError) else 'Inspect local diagnostics; no secrets printed'
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__, 'message': msg}))
        return 2


if __name__ == '__main__':
    sys.exit(main())

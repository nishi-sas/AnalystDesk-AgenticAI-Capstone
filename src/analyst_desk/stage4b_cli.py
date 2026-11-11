"""Stage 4B-1: run read-only parallel research from a *persisted approved* Stage 4A plan.

Windows CMD example:
 python -m analyst_desk.stage4b_cli run --thread-id <approved_stage4a_thread>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from .stage4a_config import PROJECT_ROOT, load_planner_settings
from .stage4a_graph import build_planning_graph, offline_planner
from .stage4a_permissions import assert_tool_permission
from .stage4b_research import ResearchError, build_research_graph


class MCPResearchGateway:
    """FastMCP in-memory protocol gateway. No raw tool invocation bypasses role policy."""

    def __init__(self, root: Path):
        self.root = root
        self._stack: AsyncExitStack | None = None
        self._clients: dict[str, Any] = {}
        self._tools: dict[str, str] = {}

    async def __aenter__(self):
        from fastmcp import Client
        from .kb_service import FilingsKnowledgeBase
        from .kb_mcp_server import create_server as kb_server
        from .edgar_service import EdgarFactsService
        from .edgar_mcp_server import create_server as edgar_server
        from .calculation_service import CalculationService
        from .calculation_mcp_server import create_server as calc_server

        self._stack = AsyncExitStack()
        try:
            from .verified_runtime_profile import knowledge_base_paths
            corpus_path, index_path = knowledge_base_paths(self.root)
            kb = FilingsKnowledgeBase(corpus_path, index_path)
            services = {
                'kb': kb_server(kb),
                'edgar': edgar_server(EdgarFactsService(self.root / 'data' / 'edgar_cache', offline=True)),
                'calc': calc_server(CalculationService(cache_dir=self.root / 'data' / 'edgar_cache')),
            }
            for service, server in services.items():
                client = await self._stack.enter_async_context(Client(server))
                self._clients[service] = client
                names = {t.name for t in await client.list_tools()}
                for name in names:
                    if name in self._tools:
                        raise ResearchError('Duplicate MCP tool name detected')
                    self._tools[name] = service
            required = {'search_passages', 'list_annual_filings', 'calculate_operating_margin', 'calculate_revenue_growth'}
            if not required.issubset(self._tools):
                raise ResearchError('Missing required Stage 4B MCP tools')
            return self
        except BaseException:
            await self._stack.aclose()
            raise

    async def __aexit__(self, exc_type, exc, tb):
        if self._stack:
            await self._stack.aclose()
        self._clients.clear()
        self._tools.clear()

    async def __call__(self, role: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert_tool_permission(role, name)
        if name not in self._tools:
            raise ResearchError('Requested tool is not registered with MCP gateway')
        res = await self._clients[self._tools[name]].call_tool(name, arguments)
        if not isinstance(res.data, dict):
            raise ResearchError('MCP tool returned non-dictionary response')
        return res.data


def approved_plan_from_stage4a(root: Path, thread_id: str) -> dict:
    """Independent approval check using the persisted Stage 4A SQLite checkpointer."""
    if not thread_id or len(thread_id) != 32 or any(x not in '0123456789abcdef' for x in thread_id):
        raise ResearchError('thread-id must be the 32-character Stage 4A hex ID')
    from langgraph.checkpoint.sqlite import SqliteSaver
    settings = load_planner_settings(root)
    db = root / 'data' / 'checkpoints' / 'stage4a.sqlite3'
    if not db.is_file():
        raise ResearchError('Stage 4A plan checkpoint database is missing')
    with SqliteSaver.from_conn_string(str(db)) as checkpointer:
        graph = build_planning_graph(settings, planner=offline_planner, checkpointer=checkpointer)
        snapshot = graph.get_state({'configurable': {'thread_id': thread_id}})
        values = snapshot.values or {}
        if values.get('status') != 'PLAN_APPROVED' or values.get('plan_approved') is not True or values.get('cancelled') is True or snapshot.next:
            raise ResearchError('Stage 4A plan has not received final human approval')
        from .stage4b_research import check_approved_plan
        candidates = values.get('candidate_tickers')
        if not isinstance(candidates, list) or not candidates or not set(candidates).issubset(set(settings.allowed_tickers)):
            raise ResearchError('Original requested-ticker scope is missing from Stage 4A checkpoint')
        return check_approved_plan(values.get('plan'), approved=True,
                                   allowed=tuple(candidates), budget=settings.token_budget)


async def run(root: Path, thread_id: str) -> dict:
    plan = approved_plan_from_stage4a(root, thread_id)
    settings = load_planner_settings(root)
    async with MCPResearchGateway(root) as gateway:
        graph = build_research_graph(call=gateway, allowed=settings.allowed_tickers, budget=settings.token_budget)
        final = await graph.ainvoke({'plan': plan, 'approved': True, 'research_results': []})
    if final.get('status') != 'RESEARCH_EVIDENCE_READY':
        raise ResearchError('Research graph did not complete')
    return {'status': 'PASS', 'phase': 'STAGE4B_RESEARCH_EVIDENCE_READY',
            'transport': 'FastMCP in-memory protocol', 'orchestration': 'LangGraph Send parallel fan-out',
            'source_thread_id': thread_id, 'approved_plan_consumed': True,
            'publication_performed': False, 'companies': sorted(final['research_results'], key=lambda r: plan['companies'].index(r['ticker'])), 'summary': final['summary']}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Stage 4B: read-only SEC agent fan-out from approved LangGraph plan')
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(run(args.project_root.resolve(), args.thread_id)), indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Never serialize exception chains, raw model content or credentials.
        message = str(exc) if isinstance(exc, ResearchError) else 'See local diagnostic logs; no secrets printed'
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__, 'message': message}))
        return 2


if __name__ == '__main__':
    sys.exit(main())

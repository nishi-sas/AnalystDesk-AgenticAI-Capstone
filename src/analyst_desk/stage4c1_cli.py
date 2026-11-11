"""Stage 4C-1 Windows entrypoint: real approved thread -> audited B-3 -> draft file."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT, load_planner_settings
from .stage4b_cli import approved_plan_from_stage4a
from .stage4b_research import ResearchError
from .stage4b3_cli import run as run_stage4b3
from .stage4c1_writer import OpenRouterReportWriter, build_writer_graph


async def run(root: Path, thread_id: str, *, offline: bool = False, no_writer_llm: bool = False, output: str = 'evidence/49_stage4c1_draft.md') -> dict:
    # Reject dangerous output paths BEFORE launching MCP/LLM work.
    location = (root / output).resolve()
    evidence_dir = (root / 'evidence').resolve()
    if location.suffix.lower() != '.md' or not location.is_relative_to(evidence_dir) or location == evidence_dir:
        raise ResearchError('Draft output must be a .md file under project evidence/')
    # --offline disables ALL model calls; --no-writer-llm skips only the extra writer call.
    # Approved plan is reloaded independently from Stage 4A checkpoint (not from model response).
    plan = approved_plan_from_stage4a(root, thread_id)
    settings = load_planner_settings(root)
    evidence = await run_stage4b3(root, thread_id, no_llm=offline)
    writer = None if offline or no_writer_llm else OpenRouterReportWriter(settings, root=root)
    graph = build_writer_graph(allowed=settings.allowed_tickers, budget=settings.token_budget, writer=writer)
    state = graph.invoke({'plan': plan, 'evidence': evidence, 'thread_id': thread_id})
    if state.get('status') != 'DRAFT_UNREVIEWED':
        raise ResearchError('Writer graph did not complete')
    draft = state['draft']
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(draft.pop('draft_markdown'), encoding='utf-8')
    draft['draft_out'] = str(location.relative_to(root)).replace('\\', '/')
    return draft


def main(argv=None):
    parser = argparse.ArgumentParser(description='Stage 4C-1: write UNREVIEWED source-constrained draft')
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--thread-id', required=True)
    parser.add_argument('--offline', action='store_true', help='No OpenRouter calls; only evidence-indexed draft')
    parser.add_argument('--no-writer-llm', action='store_true',
                        help='Skip only the extra writer model call; Stage 4B-3 still performs risk synthesis')
    parser.add_argument('--draft-out', default='evidence/49_stage4c1_draft.md')
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(run(args.project_root.resolve(), args.thread_id,
                                         offline=args.offline, no_writer_llm=args.no_writer_llm, output=args.draft_out)),
                         indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        safe = str(exc) if isinstance(exc, ResearchError) else 'See private diagnostics; credentials are not logged'
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__, 'message': safe}))
        return 2


if __name__ == '__main__':
    sys.exit(main())

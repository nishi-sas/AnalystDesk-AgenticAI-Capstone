"""Stage 4C-2: approved plan -> new Writer draft -> compliance report; no portal writes."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT, load_planner_settings
from .stage4b_cli import MCPResearchGateway, approved_plan_from_stage4a
from .stage4b_research import ResearchError
from .stage4b3_cli import run as run_b3
from .stage4c1_writer import OpenRouterReportWriter, produce_draft
from .stage4c2_critic import OpenRouterComplianceCritic, review_report


def _safe_path(root: Path, name: str, suffix: str) -> Path:
    target = (root / name).resolve()
    evidence = (root / 'evidence').resolve()
    if target.suffix.lower() != suffix or not target.is_relative_to(evidence) or target == evidence:
        raise ResearchError('Stage 4C-2 outputs must remain inside evidence/ with appropriate extensions')
    return target


async def run(root: Path, thread_id: str, *, offline: bool = False,
              draft_out: str = 'evidence/52_stage4c2_reviewed_draft.md',
              review_out: str = 'evidence/52_stage4c2_critic.json') -> dict:
    draft_path = _safe_path(root, draft_out, '.md')
    review_path = _safe_path(root, review_out, '.json')
    settings = load_planner_settings(root)
    plan = approved_plan_from_stage4a(root, thread_id)
    evidence = await run_b3(root, thread_id, no_llm=offline)
    writer = None if offline else OpenRouterReportWriter(settings, root=root)
    draft = produce_draft(plan, evidence, thread_id=thread_id, allowed=settings.allowed_tickers,
                          budget=settings.token_budget, writer=writer)
    critic = None if offline else OpenRouterComplianceCritic(settings, root=root)
    async with MCPResearchGateway(root) as gateway:
        review = await review_report(plan, evidence, draft, thread_id=thread_id,
                                     allowed=settings.allowed_tickers, budget=settings.token_budget,
                                     call=gateway, model=critic)
    # Save only after report and evidence reviews return a successful state.
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(draft['draft_markdown'], encoding='utf-8')
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return {k: v for k, v in review.items() if k != 'findings'} | {
        'review_finding_summary': {status: sum(1 for f in review['findings'] if f['verdict'] == status)
                                   for status in ('SUPPORTED', 'UNSUPPORTED', 'UNCERTAIN', 'NOT_REVIEWED')},
        'draft_out': str(draft_path.relative_to(root)).replace('\\', '/'),
        'review_out': str(review_path.relative_to(root)).replace('\\', '/'),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Stage 4C-2 independent compliance critic; no approval or publication')
    p.add_argument('command', choices=['run'])
    p.add_argument('--thread-id', required=True)
    p.add_argument('--offline', action='store_true', help='Deterministic audit only, no model calls')
    p.add_argument('--draft-out', default='evidence/52_stage4c2_reviewed_draft.md')
    p.add_argument('--review-out', default='evidence/52_stage4c2_critic.json')
    p.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    args = p.parse_args(argv)
    try:
        result = asyncio.run(run(args.project_root.resolve(), args.thread_id,
                                 offline=args.offline, draft_out=args.draft_out,
                                 review_out=args.review_out))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        safe = str(exc) if isinstance(exc, ResearchError) else 'See private diagnostics; credentials and raw SEC/LLM text are not logged'
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__, 'message': safe}))
        return 2


if __name__ == '__main__':
    sys.exit(main())

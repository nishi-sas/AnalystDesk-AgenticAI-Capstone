"""Stage 4C-3: approved filing report, up to two narrow revisions, human approval not performed."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT, load_planner_settings
from .stage4b_cli import MCPResearchGateway, approved_plan_from_stage4a
from .stage4b_research import ResearchError
from .stage4b3_cli import run as run_b3
from .stage4c1_writer import OpenRouterReportWriter
from .stage4c2_critic import OpenRouterComplianceCritic
from .stage4c3_revision import OpenRouterTargetedRewriter, run_revision_graph


def output_prefix(root: Path, name: str) -> Path:
    if not isinstance(name,str) or not re.fullmatch(r'evidence/[a-zA-Z0-9_\-]{6,90}',name.replace('\\','/')):
        raise ResearchError('Revision output prefix must be evidence/<safe_name> without extension')
    path = (root / name).resolve()
    if not path.is_relative_to((root/'evidence').resolve()):
        raise ResearchError('Revision output attempted directory traversal')
    return path


async def run(root: Path, thread_id: str, *, offline: bool = False,
              prefix: str = 'evidence/55_stage4c3_revision', max_revisions: int = 2,
              reflexion_analyst_id: str | None = None) -> dict:
    target = output_prefix(root, prefix)
    settings = load_planner_settings(root)
    if offline and reflexion_analyst_id is not None:
        raise ResearchError('Reflexion lessons require a live Writer; --offline cannot use them')
    plan = approved_plan_from_stage4a(root, thread_id)
    editorial_lessons = []
    if reflexion_analyst_id is not None:
        from .phase7c_safety import guarded_editorial_lessons as retrieve_editorial_lessons
        editorial_lessons = retrieve_editorial_lessons(
            root, analyst_id=reflexion_analyst_id,
            company_scope=tuple(sorted(plan['companies'])), exclude_thread_id=thread_id)
    evidence = await run_b3(root, thread_id, no_llm=offline)
    writer = None if offline else OpenRouterReportWriter(
        settings, root=root, editorial_lessons=editorial_lessons)
    critic = None if offline else OpenRouterComplianceCritic(settings, root=root)
    rewriter = None if offline else OpenRouterTargetedRewriter(settings, root=root)
    async with MCPResearchGateway(root) as gateway:
        result = await run_revision_graph(plan, evidence, thread_id=thread_id,
                                         allowed=settings.allowed_tickers,
                                         budget=settings.token_budget,
                                         call=gateway, writer=writer,
                                         critic=critic, rewriter=rewriter,
                                         max_revisions=max_revisions)
    # Refuse accidental overwrite of earlier evidence runs.
    paths = [(target.parent / (target.name + f'_v{v["version"]}_draft.md'),
              target.parent / (target.name + f'_v{v["version"]}_review.json')) for v in result['versions']]
    manifest = target.parent / (target.name + '_manifest.json')
    for p in [manifest] + [f for pair in paths for f in pair]:
        if p.exists():
            raise ResearchError('Revision output already exists; choose a new --prefix to preserve evidence')
    target.parent.mkdir(parents=True,exist_ok=True)
    for version, (draft_path, review_path) in zip(result['versions'], paths):
        draft_path.write_text(version['draft']['draft_markdown'],encoding='utf-8')
        review_path.write_text(json.dumps(version['review'],indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    manifest_data = {'status':result['status'],'phase':result['phase'],'thread_id':thread_id,
                     'revision_count':result['revision_count'], 'max_revisions':max_revisions,
                     'revision_actions':result['revision_actions'],
                     'revision_failure':result.get('revision_failure'),
                     'versions':[{'version':v['version'],'draft_sha256':v['draft_sha256'],
                                  'draft_path':str(pair[0].relative_to(root)).replace('\\','/'),
                                  'review_path':str(pair[1].relative_to(root)).replace('\\','/'),
                                  'hard_blockers':v['review']['hard_blockers'],
                                  'review_disposition':v['review']['review_disposition']}
                                 for v,pair in zip(result['versions'],paths)],
                     'hard_blockers':result['hard_blockers'],
                     'human_report_approved':False,'report_submitted_for_review':False,
                     'publication_performed':False,
                     'reflexion_enabled':reflexion_analyst_id is not None,
                     'reflexion_lessons_applied':len(editorial_lessons)}
    manifest.write_text(json.dumps(manifest_data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return {**manifest_data,'manifest_path':str(manifest.relative_to(root)).replace('\\','/')}


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description='Stage 4C-3 bounded revision and critic re-review; never approves or publishes')
    parser.add_argument('command',choices=['run'])
    parser.add_argument('--thread-id',required=True)
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--reflexion-analyst-id',default=None)
    parser.add_argument('--max-revisions',type=int,choices=[0,1,2],default=2)
    parser.add_argument('--prefix',default='evidence/55_stage4c3_revision')
    parser.add_argument('--project-root',type=Path,default=PROJECT_ROOT)
    args=parser.parse_args(argv)
    try:
        result=asyncio.run(run(args.project_root.resolve(),args.thread_id,offline=args.offline,
                               prefix=args.prefix,max_revisions=args.max_revisions,
                               reflexion_analyst_id=args.reflexion_analyst_id))
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    except Exception as exc:
        safe=str(exc) if isinstance(exc,ResearchError) else 'Internal failure; raw model output and credentials are not logged'
        print(json.dumps({'status':'ERROR','error_type':type(exc).__name__,'message':safe}))
        return 2


if __name__=='__main__':
    sys.exit(main())

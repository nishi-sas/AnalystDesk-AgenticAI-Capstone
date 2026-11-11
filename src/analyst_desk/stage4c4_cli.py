"""Stage 4C-4: local research portal handoff, never signs human reviews."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from .stage4a_config import PROJECT_ROOT
from .stage4a_permissions import assert_tool_permission
from .stage4b_cli import approved_plan_from_stage4a
from .stage4b_research import ResearchError, _tool_data
from .stage4c4_portal import PortalMCPGateway, load_reviewed_bundle, register_reviewed_draft


async def execute(root: Path, args) -> dict:
    if args.command == 'register':
        # Read the persisted human-approved LangGraph checkpoint first.
        plan=approved_plan_from_stage4a(root,args.thread_id)
        bundle=load_reviewed_bundle(root,args.thread_id,args.manifest,
                                    approved_companies=tuple(plan['companies']))
        # Phase 6D-2: verify real SEC-backed percentages BEFORE an MCP write.
        # Mixed revenue concepts are allowed only in an explicitly blocked draft.
        from .phase6d2_financial_integrity import verify_financial_draft
        from .edgar_service import EdgarFactsService
        verify_financial_draft(bundle, tuple(plan['companies']),
                               edgar=EdgarFactsService(root / 'data' / 'edgar_cache', offline=True))
        async with PortalMCPGateway(root) as portal:
            return await register_reviewed_draft(bundle,portal)
    if not isinstance(args.report_id,str) or re.fullmatch(r'[0-9a-f]{32}',args.report_id) is None:
        raise ResearchError('Stage 4C-4 requires a valid portal report ID')
    async with PortalMCPGateway(root) as portal:
        assert_tool_permission('writer','get_report')
        stored=_tool_data(await portal('writer','get_report',{'report_id':args.report_id}),'get_report')
        if args.command == 'status':
            return {'status':'PASS','phase':'STAGE4C_PORTAL_STATUS',
                    'report_id':stored['report_id'], 'revision':stored['revision'],
                    'portal_status':stored['status'], 'draft_sha256':stored['body_sha256'],
                    'hard_blockers':stored['open_blockers'],
                    'human_report_approved':stored['status'] in {'APPROVED','PUBLISHED'},
                    'publication_performed':stored['status']=='PUBLISHED'}
        if args.command == 'submit':
            if stored['status'] != 'DRAFT':
                raise ResearchError('Stage 4C-4 can submit only a current DRAFT')
            if stored['open_blockers']:
                return {'status':'PASS','phase':'STAGE4C_PORTAL_SUBMISSION_BLOCKED',
                        'report_id':stored['report_id'],'revision':stored['revision'],
                        'hard_blockers':stored['open_blockers'],
                        'submitted_for_review':False,'human_report_approved':False,
                        'publication_performed':False}
            assert_tool_permission('writer','submit_for_review')
            receipt=_tool_data(await portal('writer','submit_for_review',{
                'report_id':stored['report_id'],
                'expected_revision':stored['revision']}),'submit_for_review')
            if receipt.get('status')!='IN_REVIEW' or receipt.get('body_sha256')!=stored['body_sha256']:
                raise ResearchError('Stage 4C-4 reviewer handoff integrity check failed')
            return {'status':'PASS','phase':'STAGE4C_AWAITING_SIGNED_HUMAN_REVIEW',
                    'report_id':stored['report_id'],'revision':receipt['revision'],
                    'draft_sha256':receipt['body_sha256'], 'submitted_for_review':True,
                    'human_report_approved':False,'publication_performed':False}
    raise ResearchError('Unknown Stage 4C-4 command')


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description='Stage 4C-4: portal draft and separate human approval handoff')
    sub=parser.add_subparsers(dest='command',required=True)
    a=sub.add_parser('register',help='Register a reviewed Stage 4C-3 version as a local DRAFT only')
    a.add_argument('--thread-id',required=True)
    a.add_argument('--manifest',required=True,help='Existing Stage 4C-3 evidence/*_manifest.json')
    for command in ('status','submit'):
        a=sub.add_parser(command)
        a.add_argument('--report-id',required=True)
    parser.add_argument('--project-root',type=Path,default=PROJECT_ROOT)
    args=parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(execute(args.project_root.resolve(),args)),
                         indent=2,ensure_ascii=False))
        return 0
    except Exception as exc:
        safe=str(exc) if isinstance(exc,ResearchError) else 'Internal failure; credentials and source text are not logged'
        print(json.dumps({'status':'ERROR','error_type':type(exc).__name__,'message':safe}))
        return 2

if __name__=='__main__':
    sys.exit(main())

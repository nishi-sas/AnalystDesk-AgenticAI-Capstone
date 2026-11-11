"""Stage 4C-4: bind a reviewed Stage 4C-3 output to the signed HITL portal.

Only registers an UNAPPROVED local draft. Human signing is restricted to the
pre-existing interactive portal_review_cli. Publication is never automatic.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .stage4a_permissions import assert_tool_permission
from .stage4b_research import ResearchError, _tool_data
from .phase6b_output import run_output_guardrails, assert_portal_tool_arguments

_SHA = re.compile(r'^[0-9a-f]{64}$')
_HEX32 = re.compile(r'^[0-9a-f]{32}$')
_PASSAGE = r'[A-Z]{1,10}_\d{4}-\d{2}-\d{2}_Item(?:1A|7|8)_\d{5}'
_FACT = r'CIK\d{10}\|\d{10}-\d{2}-\d{6}\|us-gaap:[A-Za-z][A-Za-z0-9]*\|\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}\|USD'
_SOURCE = re.compile(r'`(' + _PASSAGE + '|' + _FACT + r')`')
_ALLOWED_PHASES = {'STAGE4C_REVIEW_BLOCKED', 'STAGE4C_READY_FOR_HUMAN_REVIEW',
                   'STAGE4C_REVISION_LIMIT_REACHED', 'STAGE4C_SEMANTIC_REVIEW_PENDING'}
_CLAIMS = {'cyber_privacy','ai_ip','competition_regulation','service_infrastructure',
           'executive_summary'}


def _inside_evidence(root: Path, name: Any, suffix: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r'evidence/[A-Za-z0-9_.-]{5,150}' + re.escape(suffix), name.replace('\\', '/')):
        raise ResearchError('Stage 4C-4 requires a simple evidence/ filename with suffix ' + suffix)
    target = (root / name).resolve()
    if not target.is_relative_to((root / 'evidence').resolve()) or not target.is_file():
        raise ResearchError('Stage 4C-4 evidence path unavailable or outside evidence/')
    return target


def _file_text(path: Path, max_bytes: int) -> str:
    if path.stat().st_size > max_bytes:
        raise ResearchError('Stage 4C-4 evidence file exceeds size budget')
    return path.read_text(encoding='utf-8')


def _read_json_file(path: Path, max_bytes: int) -> dict:
    try:
        value = json.loads(_file_text(path, max_bytes))
    except (ValueError, UnicodeError):
        raise ResearchError('Stage 4C-4 evidence JSON malformed') from None
    if not isinstance(value, dict):
        raise ResearchError('Stage 4C-4 evidence JSON must be an object')
    return value


def _validate_version(version: dict, *, thread_id: str, root: Path) -> dict:
    if not isinstance(version, dict) or type(version.get('version')) is not int or version['version'] < 0:
        raise ResearchError('Stage 4C-4 invalid revision version')
    sha = version.get('draft_sha256')
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ResearchError('Stage 4C-4 invalid report SHA-256')
    markdown = _file_text(_inside_evidence(root, version.get('draft_path'), '.md'), 180000)
    if hashlib.sha256(markdown.encode('utf-8')).hexdigest() != sha:
        raise ResearchError('Stage 4C-4 report digest differs from revision manifest')
    if ('**STATUS: UNREVIEWED DRAFT' not in markdown or
            'NOT APPROVED FOR PUBLICATION' not in markdown):
        raise ResearchError('Stage 4C-4 refuses a document without draft-only status')
    review = _read_json_file(_inside_evidence(root, version.get('review_path'), '.json'), 100000)
    if (review.get('status') != 'PASS' or review.get('phase') != 'STAGE4C_CRITIC_REPORT_READY' or
            review.get('source_thread_id') != thread_id or review.get('draft_sha256') != sha or
            review.get('critic_review_performed') is not True or
            review.get('human_report_approved') is not False or
            review.get('report_submitted_for_review') is not False or
            review.get('publication_performed') is not False or
            review.get('semantic_entailment_checked') is not False):
        raise ResearchError('Stage 4C-4 rejected unbound or falsely approved critic report')
    findings = review.get('findings')
    if (not isinstance(findings, list) or not 4 <= len(findings) <= 5 or
            review.get('claim_count') != len(findings) or
            not all(isinstance(f, dict) for f in findings) or
            len({f.get('claim_id') for f in findings if isinstance(f, dict)}) != len(findings)):
        raise ResearchError('Stage 4C-4 malformed claim inventory')
    if {f.get('claim_id') for f in findings} - _CLAIMS or not set(_CLAIMS - {'executive_summary'}).issubset({f.get('claim_id') for f in findings}):
        raise ResearchError('Stage 4C-4 missing an obligatory risk theme')
    source_ids = list(dict.fromkeys(_SOURCE.findall(markdown)))
    if not source_ids or len(source_ids) > 100 or not any(s.startswith('CIK') for s in source_ids):
        raise ResearchError('Stage 4C-4 missing bounded SEC facts and citations')
    for finding in findings:
        if (finding.get('human_verified') is not False or
                finding.get('verdict') not in {'SUPPORTED','UNSUPPORTED','UNCERTAIN','NOT_REVIEWED'} or
                not isinstance(finding.get('citations'), list) or
                not set(finding['citations']).issubset(set(source_ids))):
            raise ResearchError('Stage 4C-4 rejected forged critic verdict or citation')
    if version.get('review_disposition') != review.get('review_disposition'):
        raise ResearchError('Stage 4C-4 review disposition differs from version manifest')
    blockers = review.get('hard_blockers')
    if (not isinstance(blockers, list) or len(blockers) > 50 or
            any(not isinstance(x, str) or not x or len(x)>500 for x in blockers) or
            sorted(set(blockers)) != sorted(set(version.get('hard_blockers', [])))):
        raise ResearchError('Stage 4C-4 critic blockers differ from version manifest')
    if (review.get('model_semantic_assessment_performed') is False or
            any(f['verdict'] != 'SUPPORTED' for f in findings)) and not blockers:
        raise ResearchError('Stage 4C-4 unreviewed or non-supported findings require blockers')
    return {'sha256': sha, 'markdown': markdown, 'review': review,
            'blockers': blockers, 'source_ids': source_ids}


def load_reviewed_bundle(root: Path, thread_id: str, manifest_name: str,
                         *, approved_companies: tuple[str, ...]) -> dict:
    """Read the Stage 4C-3 files, validate their binding and preserve all blockers.

    Local files are NOT cryptographically signed. Portal's separate, interactive
    Ed25519 review is still mandatory for approval and local publication.
    """
    if not isinstance(thread_id, str) or not _HEX32.fullmatch(thread_id):
        raise ResearchError('Stage 4C-4 requires an approved Stage 4A thread ID')
    manifest = _read_json_file(_inside_evidence(root, manifest_name, '.json'), 100000)
    if (manifest.get('status') != 'PASS' or manifest.get('phase') not in _ALLOWED_PHASES or
            manifest.get('thread_id') != thread_id or
            manifest.get('human_report_approved') is not False or
            manifest.get('report_submitted_for_review') is not False or
            manifest.get('publication_performed') is not False):
        raise ResearchError('Stage 4C-4 refuses an unbound or approved revision manifest')
    versions = manifest.get('versions')
    count = manifest.get('revision_count')
    actions = manifest.get('revision_actions')
    if (not isinstance(actions, list) or len(actions)!=manifest.get('revision_count') or
            not isinstance(versions, list) or not versions or len(versions)>3 or
            type(count) is not int or count != len(versions)-1 or
            type(manifest.get('max_revisions')) is not int or
            not 0 <= count <= manifest['max_revisions'] <= 2):
        raise ResearchError('Stage 4C-4 revision-count mismatch')
    checked = []
    for index, version in enumerate(versions):
        if version.get('version') != index:
            raise ResearchError('Stage 4C-4 nonsequential version chain')
        checked.append(_validate_version(version, thread_id=thread_id, root=root))
    final = checked[-1]
    if sorted(set(manifest.get('hard_blockers', []))) != sorted(set(final['blockers'])):
        raise ResearchError('Stage 4C-4 final blocker mismatch')
    if (manifest['phase'] == 'STAGE4C_READY_FOR_HUMAN_REVIEW') != (not final['blockers']):
        raise ResearchError('Stage 4C-4 phase and blockers are inconsistent')
    if not isinstance(approved_companies, tuple) or not approved_companies:
        raise ResearchError('Stage 4C-4 approved company scope is missing')
    for source in final['source_ids']:
        if source.startswith('CIK'):
            continue
        if source.split('_',1)[0] not in approved_companies:
            raise ResearchError('Stage 4C-4 SEC passage outside approved company scope')
    for company in approved_companies:
        if not any(s.startswith(company+'_') for s in final['source_ids']):
            raise ResearchError('Stage 4C-4 report does not cite every approved company')
    return {'thread_id':thread_id, 'manifest_path':manifest_name,
            'revision_count':count, 'phase':manifest['phase'], **final}


async def register_reviewed_draft(bundle: dict, call) -> dict:
    """MCP write uses writer role only; no submission, signing or publication."""
    if not isinstance(bundle, dict) or not bundle.get('source_ids') or not isinstance(bundle.get('blockers'), list):
        raise ResearchError('Stage 4C-4 missing validated bundle')
    # Mandatory deterministic output-policy audit before any draft creation.
    output_decision = run_output_guardrails(bundle)
    if not output_decision.passed:
        raise ResearchError('Phase 6B output security blocked: ' + ','.join(output_decision.block_codes))
    title = 'AnalystDesk SEC research — ' + bundle['thread_id'][:12]
    assert_tool_permission('writer','create_report_draft')
    created = _tool_data(await call('writer', 'create_report_draft', {
        'title':title, 'markdown':bundle['markdown'],
        'source_ids':bundle['source_ids'], 'open_blockers':bundle['blockers']}), 'create_report_draft')
    assert_tool_permission('writer','get_report')
    report = _tool_data(await call('writer', 'get_report', {'report_id': created['report_id']}), 'get_report')
    if (created.get('status') != 'DRAFT' or created.get('revision') != 1 or
            report.get('status') != 'DRAFT' or report.get('revision') != 1 or
            created.get('body_sha256') != bundle['sha256'] or
            report.get('body_sha256') != bundle['sha256'] or
            report.get('markdown') != bundle['markdown'] or
            report.get('source_ids') != bundle['source_ids'] or
            report.get('open_blockers') != bundle['blockers']):
        raise ResearchError('Stage 4C-4 portal read-back mismatches reviewed report')
    return {'status':'PASS','phase':'STAGE4C_PORTAL_DRAFT_BLOCKED' if bundle['blockers'] else 'STAGE4C_PORTAL_DRAFT_READY',
            'thread_id':bundle['thread_id'],'report_id':report['report_id'],
            'revision':1,'draft_sha256':bundle['sha256'], 'source_count':len(bundle['source_ids']),
            'hard_blockers':bundle['blockers'], 'portal_status':'DRAFT',
            'critic_review_bound':True, 'submitted_for_review':False,
            'human_report_approved':False,'publication_performed':False}


class PortalMCPGateway:
    """FastMCP protocol; never exposes sign or direct service references to the caller."""
    def __init__(self, root: Path):
        self.root=root
        self.client=None

    async def __aenter__(self):
        from fastmcp import Client
        from .portal_service import PortalService
        from .portal_mcp_server import create_server
        self.client=Client(create_server(PortalService(
            self.root/'data'/'research_portal'/'portal.sqlite3',
            self.root/'data'/'research_portal'/'reviewer_public.pem')))
        await self.client.__aenter__()
        names={t.name for t in await self.client.list_tools()}
        if not {'create_report_draft','get_report','submit_for_review','publish_report'}.issubset(names) or 'approve_report' in names or 'record_signed_review' in names:
            await self.client.__aexit__(None,None,None)
            raise ResearchError('Stage 4C-4 portal MCP tool surface invalid')
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.client:
            await self.client.__aexit__(exc_type, exc, tb)
            self.client=None

    async def __call__(self, role: str, name: str, arguments: dict[str, Any]) -> dict:
        assert_tool_permission(role,name)
        assert_portal_tool_arguments(role,name,arguments)
        if name not in {'create_report_draft','get_report','submit_for_review','publish_report'}:
            raise ResearchError('Stage 4C-4 rejected unrelated MCP tool')
        response=await self.client.call_tool(name,arguments)
        if not isinstance(response.data,dict):
            raise ResearchError('Stage 4C-4 MCP reply is not structured')
        return response.data

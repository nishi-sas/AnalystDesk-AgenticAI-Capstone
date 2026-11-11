"""Phase 6D-3: nonpublishing MCP, key, permission and packaging assessment.

All runtime portal operations use a disposable SQLite database and ephemeral keys.
No real portal record is ever modified; no credential values enter receipts.
"""
from __future__ import annotations

import ast
from contextlib import closing
import asyncio
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .portal_service import PortalService
from .portal_review_cli import default_private_key
from .stage4a_permissions import assert_tool_permission, ToolPermissionError
from .phase6b_output import assert_portal_tool_arguments
from .stage4c4_portal import PortalMCPGateway

_SOURCE = 'MSFT_2026-06-30_Item1A_00011'
_BODY = '### Independent SEC test finding\n' + _SOURCE
_TITLE = 'Isolated Phase 6D-3 test'
_BLOCKER = 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'
_SECRET_RE = re.compile(rb'(?:nvapi-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
_ENV_LINE = re.compile(rb'(?im)^\s*(?:OPENROUTER_API_KEY|NVIDIA_API_KEY|HF_TOKEN|AWS_SECRET_ACCESS_KEY)\s*=\s*(?!YOUR_|<|\$\{|"?example\b)[^\s#]{8,}')

class SecurityAuditError(RuntimeError):
    pass


def _check(condition: bool, code: str) -> str:
    if not condition:
        raise SecurityAuditError(code)
    return code


def _portal_mcp_tool_names(root: Path) -> set[str]:
    path = root / 'src' / 'analyst_desk' / 'portal_mcp_server.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    exposed = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Attribute) and decorator.attr == 'tool' and isinstance(decorator.value, ast.Name) and decorator.value.id == 'mcp':
                    exposed.add(node.name)
    return exposed


def _check_gateway_denials() -> list[str]:
    checks = []
    for role, name in [('writer','publish_report'),('filing_researcher','create_report_draft'),
                       ('quant','publish_report'),('publisher','create_report_draft'),
                       ('writer','record_signed_review'),('publisher','execute_code'),
                       ('publisher','approve_report')]:
        try:
            assert_tool_permission(role,name)
        except ToolPermissionError:
            checks.append('DENIED_'+role.upper()+'_'+name.upper())
        else:
            raise SecurityAuditError('UNAUTHORIZED_TOOL_ALLOWED')
    args = [
        ('publisher','publish_report',{'report_id':'../etc','expected_sha256':'a'*64}),
        ('publisher','publish_report',{'report_id':'a'*32,'expected_sha256':'a'*64,'private_key':'bad'}),
        ('publisher','publish_report',{'report_id':'a'*32,'expected_sha256':'wrong'}),
        ('writer','submit_for_review',{'report_id':'a'*32,'expected_revision':0}),
        ('writer','create_report_draft',{'title':'x','markdown':'body','source_ids':['fake']}),
    ]
    for role, name, params in args:
        try:
            assert_portal_tool_arguments(role,name,params)
        except (ValueError, ToolPermissionError):
            checks.append('SCHEMA_DENIED_'+str(len(checks)+1))
        else:
            raise SecurityAuditError('UNAUTHORIZED_ARGUMENT_ALLOWED')
    # The gateway must reject before any MCP transport call is attempted.
    class NoDispatchClient:
        async def call_tool(self, *args, **kwargs):
            raise AssertionError('Unauthorized tool reached MCP dispatch')
    async def probe():
        gateway=PortalMCPGateway(Path('.'))
        gateway.client=NoDispatchClient()
        try:
            await gateway('writer','publish_report',{'report_id':'a'*32,'expected_sha256':'a'*64})
        except ToolPermissionError:
            return True
        return False
    _check(asyncio.run(probe()),'GATEWAY_REFUSED_BEFORE_DISPATCH')
    checks.append('GATEWAY_REFUSED_BEFORE_DISPATCH')
    return checks


def _ephemeral_portal_tests() -> list[str]:
    checks=[]
    with tempfile.TemporaryDirectory(prefix='analystdesk_phase6d3_') as tmp:
        t=Path(tmp)
        key=Ed25519PrivateKey.generate()
        pub=t/'reviewer_public.pem'
        pub.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        portal=PortalService(t/'isolated.sqlite3',pub)
        _check(portal.portal_status()['data']['external_publication'] is False,'LOCAL_ONLY_PORTAL')
        checks.append('LOCAL_ONLY_PORTAL')
        blocked=portal.create_report_draft(_TITLE,_BODY,[_SOURCE],[_BLOCKER])['data']
        _check(blocked['status']=='DRAFT','BLOCKED_DRAFT_STAYS_DRAFT')
        checks.append('BLOCKED_DRAFT_STAYS_DRAFT')
        denied=portal.submit_for_review(blocked['report_id'],1)
        _check(denied.get('error_code')=='OPEN_BLOCKERS','BLOCKER_REFUSES_SUBMISSION')
        checks.append('BLOCKER_REFUSES_SUBMISSION')
        denied=portal.publish_report(blocked['report_id'],blocked['body_sha256'])
        _check(not denied['ok'],'BLOCKER_REFUSES_PUBLICATION')
        checks.append('BLOCKER_REFUSES_PUBLICATION')
        ready=portal.create_report_draft(_TITLE,_BODY,[_SOURCE])['data']
        rid=ready['report_id'];digest=ready['body_sha256']
        denied=portal.publish_report(rid,digest)
        _check(denied.get('error_code')=='APPROVAL_REQUIRED','UNAPPROVED_PUBLICATION_DENIED')
        checks.append('UNAPPROVED_PUBLICATION_DENIED')
        _check(portal.submit_for_review(rid,1)['ok'],'REVIEW_SUBMISSION')
        checks.append('REVIEW_SUBMISSION')
        wrong=portal.record_signed_review(rid,'Test reviewer','APPROVE',Ed25519PrivateKey.generate())
        _check(wrong.get('error_code')=='APPROVAL_INVALID','WRONG_SIGNER_REFUSED')
        checks.append('WRONG_SIGNER_REFUSED')
        valid=portal.record_signed_review(rid,'Test reviewer','APPROVE',key)
        _check(valid['ok'],'ISOLATED_VALID_SIGNATURE')
        checks.append('ISOLATED_VALID_SIGNATURE')
        # Tamper only with scratch SQLite receipt. The signature verification MUST reject.
        with closing(sqlite3.connect(t/'isolated.sqlite3')) as conn, conn:
            conn.execute('UPDATE review_receipts SET signature_hex=? WHERE report_id=?',('00'*64,rid))
        denied=portal.publish_report(rid,digest)
        _check(denied.get('error_code')=='APPROVAL_INVALID','TAMPERED_SIGNATURE_DENIED')
        checks.append('TAMPERED_SIGNATURE_DENIED')
        # Approval for revision 1 must not authorize revision 2.
        changed=portal.revise_report_draft(rid,1,_BODY+'\nEdited',[_SOURCE])
        _check(changed['ok'] and changed['data']['status']=='DRAFT','EDIT_INVALIDATED_APPROVAL')
        checks.append('EDIT_INVALIDATED_APPROVAL')
        _check(portal.publish_report(rid,changed['data']['body_sha256']).get('error_code')=='APPROVAL_REQUIRED','STALE_APPROVAL_DENIED')
        checks.append('STALE_APPROVAL_DENIED')
        _check(portal.submit_for_review(rid,1).get('error_code')=='VERSION_CONFLICT','STALE_REVISION_DENIED')
        checks.append('STALE_REVISION_DENIED')
        rejected=portal.create_report_draft(_TITLE,_BODY,[_SOURCE])['data']
        _check(portal.submit_for_review(rejected['report_id'],1)['ok'],'SECOND_SUBMIT')
        _check(portal.record_signed_review(rejected['report_id'],'Test reviewer','REJECT',key)['ok'],'ISOLATED_REJECTION')
        _check(portal.publish_report(rejected['report_id'],rejected['body_sha256']).get('error_code')=='APPROVAL_REQUIRED','REJECTED_PUBLICATION_DENIED')
        checks.append('REJECTED_PUBLICATION_DENIED')
        with closing(sqlite3.connect(t/'isolated.sqlite3')) as conn, conn:
            n=conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0]
        _check(n==0,'ZERO_ISOLATED_PUBLICATIONS')
        checks.append('ZERO_ISOLATED_PUBLICATIONS')
    return checks


def scan_submission_zip(path: Path) -> dict[str, Any]:
    """Inspect an actual candidate submission archive; never print its contents."""
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise SecurityAuditError('SUBMISSION_ZIP_MISSING_OR_INVALID')
    findings=[]
    forbidden_suffixes={'.pem','.key','.p12','.pfx','.sqlite3','.db','.env'}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir(): continue
            p=Path(info.filename.replace('\\','/'))
            parts={s.lower() for s in p.parts}
            name=p.name.lower()
            forbidden=(name=='.env' or name.startswith('.env.') and name!='.env.example' or p.suffix.lower() in forbidden_suffixes or
                       'edgar_cache' in parts or '__pycache__' in parts or '.git' in parts or 'research_portal' in parts or
                       'private' in name and ('key' in name or 'reviewer' in name))
            if forbidden:
                findings.append({'file':str(p),'reason':'FORBIDDEN_PATH'})
                continue
            if info.file_size > 10_000_000:
                findings.append({'file':str(p),'reason':'OVERSIZE_FILE'})
                continue
            if p.suffix.lower() not in {'.py','.md','.txt','.json','.yaml','.yml','.toml','.bat','.ps1','.csv','.html','.ipynb','.xml','.cfg','.ini'}:
                continue
            payload=z.read(info)
            if _SECRET_RE.search(payload) or _ENV_LINE.search(payload):
                findings.append({'file':str(p),'reason':'SUSPECTED_SECRET_VALUE'})
    return {'status':'PASS' if not findings else 'BLOCKED',
            'phase':'PHASE6D3_SUBMISSION_ZIP_SCAN','findings':findings,
            'file_count':len([i for i in zipfile.ZipFile(path).infolist() if not i.is_dir()]),
            'secret_values_logged':False}


def audit(root: Path) -> dict[str, Any]:
    root=root.resolve()
    expected={'create_report_draft','revise_report_draft','submit_for_review',
              'get_report','list_reports','publish_report','portal_status'}
    exposed=_portal_mcp_tool_names(root)
    _check(exposed == expected,'MCP_TOOL_SURFACE_DRIFT')
    _check(not {'approve_report','record_signed_review','execute_code','run_shell','http_request'}.intersection(exposed),'PRIVILEGED_TOOL_EXPOSED')
    _check(default_private_key().resolve().is_relative_to(root) is False,'REVIEW_KEY_LOCATION_UNSAFE')
    ignore=(root/'.gitignore')
    gitignore=ignore.read_text(encoding='utf-8') if ignore.exists() else ''
    _check(any(line.strip()=='.env' for line in gitignore.splitlines()),'ENV_NOT_GITIGNORED')
    checks=['AGENT_MCP_TOOL_SURFACE_ALLOWLIST','NO_APPROVAL_TOOL_IN_MCP','PRIVATE_KEY_DEFAULT_OUTSIDE_PROJECT','ENV_GITIGNORED']
    checks+=_check_gateway_denials()
    checks+=_ephemeral_portal_tests()
    return {'status':'PASS','phase':'PHASE6D3_PRIVILEGE_AND_SIGNING_AUDIT',
            'controls_passed':len(checks),'control_ids':checks,
            'actual_portal_opened':False,'actual_portal_registration_performed':False,
            'actual_portal_approval_performed':False,'actual_portal_publication_performed':False,
            'isolated_sqlite_only':True,'isolated_publications':0,
            'limitations':[
                'MCP tool surface verified statically from source; gateway policy and portal signing tested dynamically',
                'No production caller identity authentication at the MCP server boundary',
                'Approval private-key permissions/ACLs on the actual Windows machine not attested',
                'Calculation subprocess is not a hardened OS/network sandbox',
                'The final submission ZIP must be scanned separately; source tree audit is not a ZIP scan',
                'No live credential exposure or unauthorized network penetration test performed',
            ]}

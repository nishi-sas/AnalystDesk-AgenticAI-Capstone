"""Phase 6D-3 controls; no production database, network, or publication."""
from __future__ import annotations
import json
import zipfile
from pathlib import Path
import pytest
from analyst_desk.phase6d3_security import (
    audit,scan_submission_zip,SecurityAuditError,_portal_mcp_tool_names,
    _check_gateway_denials,_ephemeral_portal_tests)
from analyst_desk.phase6d3_cli import main
from analyst_desk.phase6b_output import assert_portal_tool_arguments
from analyst_desk.stage4a_permissions import assert_tool_permission,ToolPermissionError

ROOT=Path(__file__).resolve().parents[1]


def test_full_nonpublishing_security_audit():
    receipt=audit(ROOT)
    assert receipt['status']=='PASS'
    assert receipt['controls_passed']>=25
    assert receipt['actual_portal_publication_performed'] is False
    assert receipt['isolated_publications']==0

@pytest.mark.parametrize('name',[ 'approve_report','record_signed_review','execute_code','run_shell','http_request'])
def test_forbidden_mcp_tools_not_exposed(name):
    assert name not in _portal_mcp_tool_names(ROOT)

@pytest.mark.parametrize('role,tool',[('writer','publish_report'),('publisher','create_report_draft'),
          ('quant','publish_report'),('filing_researcher','create_report_draft'),
          ('publisher','record_signed_review'),('publisher','shell_exec')])
def test_disallowed_roles_cannot_dispatch(role,tool):
    with pytest.raises(ToolPermissionError): assert_tool_permission(role,tool)

@pytest.mark.parametrize('kwargs',[{'report_id':'../etc','expected_sha256':'a'*64},
      {'report_id':'a'*32,'expected_sha256':'a'*64,'private_key':'secret'},
      {'report_id':'a'*32,'expected_sha256':'bad'}])
def test_privileged_tool_argument_validation(kwargs):
    with pytest.raises(ValueError): assert_portal_tool_arguments('publisher','publish_report',kwargs)


def test_disposable_signatures_and_revision_integrity():
    controls=_ephemeral_portal_tests()
    assert 'TAMPERED_SIGNATURE_DENIED' in controls
    assert 'STALE_APPROVAL_DENIED' in controls
    assert 'REJECTED_PUBLICATION_DENIED' in controls
    assert 'ZERO_ISOLATED_PUBLICATIONS' in controls


def test_gateway_disallows_before_network_dispatch():
    assert 'GATEWAY_REFUSED_BEFORE_DISPATCH' in _check_gateway_denials()


def test_candidate_archive_with_source_only_passes(tmp_path):
    z=tmp_path/'candidate.zip'
    with zipfile.ZipFile(z,'w') as h:
        h.writestr('src/analyst_desk/app.py','print("hello")\n')
        h.writestr('README.md','A local educational capstone.')
    assert scan_submission_zip(z)['status']=='PASS'

@pytest.mark.parametrize('filename,contents',[
    ('.env','OPENROUTER_API_KEY=sk-sensitive'),
    ('data/research_portal/portal.sqlite3','not a real db'),
    ('data/edgar_cache/CIK0000.json','{}'),
    ('reviewer_private.pem','not a real key'),
    ('src/keys.py','TOKEN = "nvapi-ABCDEFGHIJKLMNOPQ"'),
])
def test_candidate_archive_secrets_fail_closed(tmp_path,filename,contents):
    z=tmp_path/'candidate.zip'
    with zipfile.ZipFile(z,'w') as h: h.writestr(filename,contents)
    report=scan_submission_zip(z)
    assert report['status']=='BLOCKED'
    assert report['findings']
    assert 'sk-sensitive' not in json.dumps(report)


def test_cli_writes_redacted_audit_to_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr('analyst_desk.phase6d3_cli.audit',lambda _: {'status':'PASS','phase':'MOCK','actual_portal_publication_performed':False})
    rc=main(['audit','--root',str(tmp_path),'--out','evidence/test_audit.json'])
    assert rc==0
    assert (tmp_path/'evidence'/'test_audit.json').exists()


def test_cli_rejects_output_outside_evidence(tmp_path):
    rc=main(['audit','--root',str(tmp_path),'--out','../bad.json'])
    assert rc==2
    assert not (tmp_path.parent/'bad.json').exists()

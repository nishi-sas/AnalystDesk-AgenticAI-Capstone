"""Synthetic acceptance receipts; production evidence must be validated on Windows."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from analyst_desk.phase6d4_acceptance import validate,AcceptanceError
from analyst_desk.phase6d4_cli import main


def fixtures(root):
    ev=root/'evidence';ev.mkdir()
    data={
      '87_phase6c_boundary_audit.txt':{'status':'PASS','mode':'DETERMINISTIC_POLICY_BOUNDARIES_ONLY','defences_on':{'blocked':35,'total':35}},
      '90_phase6c2_graph_replay_console.txt':{'status':'PASS','defences_on':{'blocked_before_planner':11,'benign_reached_review':8}},
      '91_phase6c2_external_audit.txt':{'correctly_tagged_untrusted':10,'downstream_resilience_verified':False},
      '93_phase6c2_live_full.txt':{'status':'PASS','attack_blocked':11,'attack_total':11,'benign_false_blocked':0,'benign_total':8,'model_verdicts_valid':19},
      '96_phase6d1_replay_console.txt':{'status':'PASS','writer_quarantined_before_model':10,'critic_quarantined_before_model':12,'benign_accepted':5,'malicious_model_invocations':{'writer':0,'critic':0}},
      '103_phase6d2_real_audit_retry.txt':{'status':'PASS_WITH_BLOCKERS','verified_metrics':4,'arithmetical_reconciliation_passed':True,'mixed_revenue_tags':['GOOGL'],'hard_blockers':['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'],'publication_performed':False,'portal_registration_performed':False,'human_report_approved':False},
      '104_phase6d3_controls.json':{'status':'PASS','phase':'PHASE6D3_PRIVILEGE_AND_SIGNING_AUDIT','controls_passed':27,'actual_portal_publication_performed':False,'isolated_publications':0},
    }
    for name,obj in data.items(): (ev/name).write_text(json.dumps(obj),encoding='utf-8')
    (ev/'105_phase6d3_full_regression.txt').write_text('==== 630 passed in 18.4s ====')
    (root/'security').mkdir();(root/'security'/'threat_model.md').write_text('# threat model')
    return data


def test_good_evidence_passes_with_residual_and_no_signoff(tmp_path):
    fixtures(tmp_path)
    got=validate(tmp_path)
    assert got['status']=='PASS_WITH_RESIDUAL_RISKS'
    assert got['sign_off']=='PENDING_HUMAN_REVIEW'
    assert not got['deployment_ready'] and not got['existing_report_publication_authorized']

@pytest.mark.parametrize('file,key,value',[
   ('93_phase6c2_live_full.txt','attack_blocked',10),
   ('96_phase6d1_replay_console.txt','writer_quarantined_before_model',9),
   ('103_phase6d2_real_audit_retry.txt','verified_metrics',3),
   ('104_phase6d3_controls.json','status','BLOCKED')])
def test_tampered_phase_receipt_refused(tmp_path,file,key,value):
    fixtures(tmp_path);p=tmp_path/'evidence'/file;obj=json.loads(p.read_text());obj[key]=value;p.write_text(json.dumps(obj))
    with pytest.raises(AcceptanceError): validate(tmp_path)


def test_reconciliation_blocker_must_remain(tmp_path):
    fixtures(tmp_path);p=tmp_path/'evidence'/'103_phase6d2_real_audit_retry.txt'
    obj=json.loads(p.read_text());obj['hard_blockers']=[];p.write_text(json.dumps(obj))
    with pytest.raises(AcceptanceError,match='FINANCIAL_BLOCKER_LOST'): validate(tmp_path)


def test_missing_final_regression_refused(tmp_path):
    fixtures(tmp_path);(tmp_path/'evidence'/'105_phase6d3_full_regression.txt').unlink()
    with pytest.raises(AcceptanceError,match='FINAL_REGRESSION_MISSING'): validate(tmp_path)


def test_cli_creates_evidence_only_without_publication(tmp_path):
    fixtures(tmp_path)
    assert main(['acceptance','--root',str(tmp_path)])==0
    receipt=json.loads((tmp_path/'evidence'/'106_phase6d4_acceptance.json').read_text())
    assert receipt['real_portal_writes_performed_by_this_audit'] is False


def test_cli_rejects_path_escape(tmp_path):
    assert main(['acceptance','--root',str(tmp_path),'--out','../no.json'])==2

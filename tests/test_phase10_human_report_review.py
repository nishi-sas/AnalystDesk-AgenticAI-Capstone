"""Local security and regression tests; no Docker, networking or OpenRouter calls."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

PATCH = Path(__file__).resolve().parents[1]
TID = "c2f3b8dc3d53480098f0cae2cbc2f9dc"
NAME = f"ui_stage4c3_{TID}_f0e2e94d_manifest.json"


class BridgeError(Exception):
    pass


def get_module(monkeypatch):
    bridge = types.ModuleType("phase10_bridge")
    bridge.BridgeError = BridgeError
    def check_thread_id(tid):
        if tid != TID:
            raise BridgeError("Bad thread ID")
        return tid
    bridge.check_thread_id = check_thread_id
    review_bridge = types.ModuleType("phase10_review_bridge")
    review_bridge.validate_review_bundle = lambda root, tid, prefix: sys.modules["human_review_test"].bound_result
    monkeypatch.setitem(sys.modules, "phase10_bridge", bridge)
    monkeypatch.setitem(sys.modules, "phase10_review_bridge", review_bridge)
    source = PATCH / "ui_patch" / "phase10_human_review.py"
    spec = importlib.util.spec_from_file_location("human_review_test", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules["human_review_test"] = module
    spec.loader.exec_module(module)
    return module


def make_result(ready=True):
    findings = [{"claim_id": "risk", "verdict": "SUPPORTED"},
                {"claim_id": "summary", "verdict": "SUPPORTED" if ready else "UNCERTAIN"}]
    review = {
        "findings": findings, "model_semantic_assessment_performed": True,
        "critic_review_performed": True, "human_report_approved": False,
        "publication_performed": False,
    }
    return {
        "thread_id": TID,
        "manifest_name": NAME,
        "draft_sha256": hashlib.sha256(b"the immutable draft").hexdigest(),
        "critic_review": review,
        "phase": "STAGE4C_READY_FOR_HUMAN_REVIEW" if ready else "STAGE4C_REVIEW_BLOCKED",
        "hard_blockers": [] if ready else ["UNSUPPORTED_OR_INSUFFICIENTLY_SUPPORTED_CLAIMS"],
        "ready_for_human_review": ready,
        "supported": 2 if ready else 1,
        "claim_count": 2,
        "revision_count": 0,
    }


def test_approved_report_records_persistent_local_receipt(tmp_path, monkeypatch):
    mod = get_module(monkeypatch)
    result = make_result()
    mod.bound_result = result
    assert mod.can_approve(result)
    reviewer, note = mod.parse_confirmation("APPROVE | Research Reviewer | Evidence checked", "APPROVE")
    rec = mod.record_decision(tmp_path, result, "APPROVE", reviewer, note)
    assert rec["approval_scope"] == "LOCAL_CHAINLIT_DEMO_ONLY"
    assert rec["portal_signed_review"] is False
    assert rec["publication_performed"] is False
    assert rec["identity_authenticated"] is False
    assert mod.read_decision(tmp_path, result) == rec
    assert "Local Chainlit capstone" in mod.receipt_markdown(rec)
    with pytest.raises(BridgeError, match="already exists"):
        mod.record_decision(tmp_path, result, "APPROVE", reviewer, note)


def test_blocked_report_cannot_be_approved(tmp_path, monkeypatch):
    mod = get_module(monkeypatch)
    result = make_result(ready=False)
    mod.bound_result = result
    assert not mod.can_approve(result)
    with pytest.raises(BridgeError, match="approval refused|Approval refused"):
        mod.record_decision(tmp_path, result, "APPROVE", "Reviewer", "No")
    assert not (tmp_path / 'docker_runtime' / 'human_review_decisions').exists()
    rec = mod.record_decision(tmp_path, result, "REQUEST_REVISION", "Reviewer", "Fix the uncertain executive summary")
    assert rec["next_step"] == "MANUAL_REVISION_REQUIRED"
    assert rec["portal_signed_review"] is False


def test_reject_blocked_report_and_cancel_no_receipt(tmp_path, monkeypatch):
    mod = get_module(monkeypatch)
    result = make_result(ready=False)
    mod.bound_result = result
    rec = mod.record_decision(tmp_path, result, "REJECT", "Reviewer", "Insufficient SEC evidence")
    assert rec["decision"] == "REJECT"
    assert rec["publication_performed"] is False


@pytest.mark.parametrize("reply,decision", [
    ("APPROVE|Nobody|Note", "REJECT"),
    ("APPROVE | A | OK", "APPROVE"),
    ("APPROVE | Reviewer | x\ny", "APPROVE"),
    (" APPROVE | Reviewer | OK", "APPROVE"),
    ("APPROVE | Reviewer", "APPROVE"),
])
def test_confirmation_fail_closed(monkeypatch, reply, decision):
    mod = get_module(monkeypatch)
    with pytest.raises(BridgeError):
        mod.parse_confirmation(reply, decision)


def test_receipt_tamper_detection(tmp_path, monkeypatch):
    mod = get_module(monkeypatch)
    result = make_result()
    mod.bound_result = result
    rec = mod.record_decision(tmp_path, result, "APPROVE", "Reviewer", "Checked")
    path = tmp_path / 'docker_runtime' / 'human_review_decisions' / (rec['local_report_id'] + '.json')
    obj = json.loads(path.read_text(encoding='utf-8'))
    obj['decision'] = 'REJECT'
    path.write_text(json.dumps(obj), encoding='utf-8')
    with pytest.raises(BridgeError, match="integrity check"):
        mod.read_decision(tmp_path, result)


def test_stale_review_refused(tmp_path, monkeypatch):
    mod = get_module(monkeypatch)
    result = make_result()
    mod.bound_result = make_result(ready=False)  # disk review changed since display
    with pytest.raises(BridgeError, match="underlying Critic review has changed"):
        mod.record_decision(tmp_path, result, "APPROVE", "Reviewer", "Approved")


def test_unsupported_phase_cannot_approve(monkeypatch):
    mod = get_module(monkeypatch)
    result = make_result()
    result['phase'] = 'STAGE4C_REVIEW_BLOCKED'
    assert not mod.can_approve(result)
    result = make_result()
    result['critic_review']['findings'][1]['verdict'] = 'UNCERTAIN'
    assert not mod.can_approve(result)
    result = make_result()
    result['critic_review']['model_semantic_assessment_performed'] = False
    assert not mod.can_approve(result)


def test_installer_matches_both_previous_versions_and_is_idempotent():
    source = PATCH / 'tools' / 'install_human_report_review.py'
    spec = importlib.util.spec_from_file_location('install_human_test', source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = PATCH / 'tests' / 'fixtures'
    with_packet = (root / 'chainlit_with_review_packet.py').read_text(encoding='utf-8')
    before_packet = (root / 'chainlit_before_review_packet.py').read_text(encoding='utf-8')
    for previous in (with_packet, before_packet):
        updated = mod.transform(previous)
        compile(updated, 'chainlit_app.py', 'exec')
        assert 'approve_human_report' in updated
        assert 'build_review_packet(result)' in updated
        assert 'REQUEST_REVISION' in updated
        assert mod.transform(updated) == updated
    with pytest.raises(ValueError):
        mod.transform('arbitrary unrelated app')

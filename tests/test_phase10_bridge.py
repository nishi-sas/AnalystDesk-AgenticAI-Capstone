"""Pure offline tests for the Phase 10 protocol and fail-closed contract."""
import asyncio
import json
import pytest
from phase10_bridge import (
    BridgeError, check_thread_id, stage4a_args, decode_sse_block, validate_completed,
    select_container_id, stage4a,
)

TID = "b3a5fcf8dbdb430ba814727b7c0dab14"


def test_thread_id_valid():
    assert check_thread_id(TID) == TID


@pytest.mark.parametrize("bad", ["", "ABC", "A"*32, "a"*31, "a"*33, "../" + "a"*32, None])
def test_thread_id_invalid(bad):
    with pytest.raises(BridgeError):
        check_thread_id(bad)


def test_stage4a_start_always_offline():
    args = stage4a_args("start", TID, request="Compare cybersecurity risks")
    assert "--offline" in args and "--model-guardrails" not in args
    assert "--request" in args and TID == args[-1]


def test_stage4a_approve_and_reject_only():
    assert stage4a_args("resume", TID, decision="APPROVE")[-1] == "APPROVE"
    assert stage4a_args("resume", TID, decision="REJECT")[-1] == "REJECT"
    with pytest.raises(BridgeError):
        stage4a_args("resume", TID, decision="EDIT")


def test_no_new_plan_without_request():
    with pytest.raises(BridgeError):
        stage4a_args("start", TID, request="tiny")


def test_decode_started():
    event, payload = decode_sse_block('event: started\ndata: {"status":"RUNNING"}')
    assert (event, payload["status"]) == ("started", "RUNNING")


@pytest.mark.parametrize("bad", ["event: unknown\ndata: {}", "event: completed\ndata: bad", "data: {}"])
def test_decode_rejects_invalid_event(bad):
    with pytest.raises(BridgeError):
        decode_sse_block(bad)


def test_validate_success_contract():
    value = {"status": "PASS", "approved_plan_consumed": True,
             "llm_synthesis_performed": False, "publication_performed": False,
             "citation_count": 23, "xbrl_fact_count": 6}
    assert validate_completed(value) == value
    for key, bad in [("status", "ERROR"), ("approved_plan_consumed", False),
                     ("llm_synthesis_performed", True), ("publication_performed", True),
                     ("citation_count", True), ("xbrl_fact_count", -1)]:
        tampered = dict(value, **{key: bad})
        with pytest.raises(BridgeError):
            validate_completed(tampered)


def test_select_container_id_exactly_one():
    assert select_container_id(b"c4da9bd4a3af\n") == "c4da9bd4a3af"


@pytest.mark.parametrize("bad", [b"", b"one\ntwo\n", b"h"*12+b"\n", b"abc\n", b"\xff"])
def test_select_container_id_fail_closed(bad):
    with pytest.raises(BridgeError):
        select_container_id(bad)


def test_stage4a_uses_running_container_without_compose(monkeypatch):
    calls = []
    async def fake_docker(cmd, *, timeout):
        calls.append(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return b"c4da9bd4a3af\n"
        return json.dumps({"thread_id": TID, "status": "PLAN_APPROVED"}).encode()
    monkeypatch.setattr("phase10_bridge._run_docker", fake_docker)
    result = asyncio.run(stage4a("status", TID))
    assert result["status"] == "PLAN_APPROVED"
    assert calls[0][:2] == ["docker", "ps"]
    assert "label=com.docker.compose.service=analystdesk-api" in calls[0]
    assert calls[1][:5] == ["docker", "exec", "-i", "c4da9bd4a3af", "python"]
    assert "compose" not in calls[1]

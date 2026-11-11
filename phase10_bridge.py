"""Local-only Phase 10 bridge. No secrets, publishing or hosted LLM calls.

Stage 4A is executed INSIDE the running Phase 9C Docker API container so planning,
review and research share the same writable SQLite checkpoint mount.
Docker's running container is located by scoped Compose labels rather than
`docker compose exec`, because compose.yaml interpolates Grafana credentials
and a separate Chainlit terminal may not have those environment variables.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_URL = "http://127.0.0.1:8000/v1/research/stream"
THREAD_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_REQUEST_CHARS = 1500
DOCKER_PROJECT = ROOT.name.lower()   # AnalystDesk -> analystdesk (current Compose project)
DOCKER_SERVICE = "analystdesk-api"
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12,64}$")


class BridgeError(RuntimeError):
    """Safe, non-sensitive error for the local demonstration interface."""


def check_thread_id(value: str) -> str:
    if not isinstance(value, str) or THREAD_RE.fullmatch(value) is None:
        raise BridgeError("Invalid thread ID; expected 32 lowercase hexadecimal characters.")
    return value


def stage4a_args(command: str, thread_id: str, *, request: str | None = None,
                 decision: str | None = None) -> list[str]:
    tid = check_thread_id(thread_id)
    if command == "start":
        if not isinstance(request, str) or not 10 <= len(request.strip()) <= MAX_REQUEST_CHARS:
            raise BridgeError("Research request must contain 10–1500 characters.")
        if decision is not None:
            raise BridgeError("Cannot supply a decision when starting a plan.")
        return ["start", "--offline", "--request", request.strip(),
                "--analyst-id", "demo_analyst", "--thread-id", tid]
    if command == "status" and request is None and decision is None:
        return ["status", "--thread-id", tid]
    if command == "resume" and request is None and decision in {"APPROVE", "REJECT"}:
        return ["resume", "--thread-id", tid, "--decision", decision]
    raise BridgeError("Unsupported Stage 4A operation.")


def select_container_id(raw: bytes) -> str:
    """Fail closed unless exactly one matching running API container is found."""
    try:
        ids = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise BridgeError("Docker returned an invalid container ID.") from exc
    if len(ids) != 1 or CONTAINER_ID_RE.fullmatch(ids[0]) is None:
        raise BridgeError(
            "Expected one running AnalystDesk API container. "
            "Check `docker compose ps` in the main environment."
        )
    return ids[0]


async def _run_docker(cmd: list[str], *, timeout: int) -> bytes:
    """Run a fixed argv without a shell; do not expose Docker stderr to the UI."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(ROOT), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise BridgeError("Docker operation timed out. Check Docker Desktop.") from None
    except FileNotFoundError as exc:
        raise BridgeError("Docker executable not found in the Chainlit terminal.") from exc
    except OSError as exc:
        raise BridgeError("Unable to execute Docker from the Chainlit terminal.") from exc
    if proc.returncode != 0:
        raise BridgeError("Docker command failed. Check Docker Desktop and terminal diagnostics.")
    return stdout


async def stage4a(command: str, thread_id: str, *, request: str | None = None,
                  decision: str | None = None) -> dict:
    """Invoke allowlisted Stage 4A commands in the existing API container.

    No shell or LLM calls. Container identity is scoped to the running
    AnalystDesk Compose project and its analystdesk-api service. Using
    `docker exec` avoids re-parsing the Grafana password requirement.
    """
    argv = stage4a_args(command, thread_id, request=request, decision=decision)
    lookup = ["docker", "ps", "--filter", f"label=com.docker.compose.project={DOCKER_PROJECT}",
              "--filter", f"label=com.docker.compose.service={DOCKER_SERVICE}",
              "--format", "{{.ID}}"]
    container_id = select_container_id(await _run_docker(lookup, timeout=20))
    cmd = ["docker", "exec", "-i", container_id, "python", "-m",
           "analyst_desk.stage4a_cli", *argv]
    try:
        stdout = await _run_docker(cmd, timeout=150)
    except BridgeError as exc:
        raise BridgeError(
            f"Stage 4A {command} failed inside Docker. "
            "Run the Stage 4A diagnostic command directly to inspect the error."
        ) from exc
    try:
        result = json.loads(stdout.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("Stage 4A returned an unreadable response.") from exc
    if not isinstance(result, dict) or result.get("thread_id") != thread_id:
        raise BridgeError("Stage 4A checkpoint identity check failed.")
    return result


def decode_sse_block(block: str) -> tuple[str, dict]:
    """Decode a complete SSE frame; fail closed on malformed/unexpected data."""
    event = None
    data = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if event not in {"started", "completed", "error"} or not data:
        raise BridgeError("Unexpected research stream event.")
    try:
        payload = json.loads("\n".join(data))
    except ValueError as exc:
        raise BridgeError("Invalid research stream JSON.") from exc
    if not isinstance(payload, dict):
        raise BridgeError("Invalid research stream payload.")
    return event, payload


def validate_completed(payload: dict) -> dict:
    if not (
        payload.get("status") == "PASS"
        and payload.get("approved_plan_consumed") is True
        and payload.get("llm_synthesis_performed") is False
        and payload.get("publication_performed") is False
        and type(payload.get("citation_count")) is int
        and payload["citation_count"] >= 0
        and type(payload.get("xbrl_fact_count")) is int
        and payload["xbrl_fact_count"] >= 0
    ):
        raise BridgeError("Research completion failed its audited contract.")
    return payload

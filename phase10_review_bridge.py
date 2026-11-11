"""Explicit opt-in Stage 4C-3 review via an isolated, short-lived Docker job.

This bridge deliberately leaves the long-running read-only FastAPI research API
unchanged. No LLM call happens without pressing the Chainlit review action.
The result is always a *human-unapproved* draft, regardless of Critic findings.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import uuid

from phase10_bridge import (
    BridgeError, ROOT, DOCKER_PROJECT, DOCKER_SERVICE,
    _run_docker, check_thread_id, select_container_id,
)

_IMAGE_RE = re.compile(r"sha256:[a-f0-9]{64}")
_RELEASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,80}")
_PREFIX_RE = re.compile(r"ui_stage4c3_[a-f0-9]{32}_[a-f0-9]{8}")
_ALLOWED_PHASES = frozenset({
    "STAGE4C_READY_FOR_HUMAN_REVIEW", "STAGE4C_REVIEW_BLOCKED",
    "STAGE4C_SEMANTIC_REVIEW_PENDING", "STAGE4C_REVISION_LIMIT_REACHED",
})
_REVIEW_LOCK = asyncio.Lock()
_MAX_REPORT_BYTES = 500_000


def validate_review_bundle(root: Path, thread_id: str, prefix_name: str) -> dict:
    """Bind manifest, versioned draft, critic report, SHA256 and approval state."""
    tid = check_thread_id(thread_id)
    if not isinstance(prefix_name, str) or _PREFIX_RE.fullmatch(prefix_name) is None:
        raise BridgeError("Invalid Stage 4C evidence prefix.")
    evidence = root / "evidence"
    manifest_path = evidence / f"{prefix_name}_manifest.json"
    try:
        if manifest_path.stat().st_size > _MAX_REPORT_BYTES:
            raise BridgeError("Stage 4C manifest exceeds the size limit.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
        raise BridgeError("Stage 4C manifest is missing or unreadable.") from exc
    if not isinstance(manifest, dict) or not (
        manifest.get("status") == "PASS"
        and manifest.get("thread_id") == tid
        and manifest.get("phase") in _ALLOWED_PHASES
        and manifest.get("human_report_approved") is False
        and manifest.get("report_submitted_for_review") is False
        and manifest.get("publication_performed") is False
    ):
        raise BridgeError("Stage 4C manifest failed its provenance/approval contract.")
    versions = manifest.get("versions")
    if not isinstance(versions, list) or not 1 <= len(versions) <= 3:
        raise BridgeError("Stage 4C output has an invalid revision count.")
    if type(manifest.get("revision_count")) is not int or manifest["revision_count"] != len(versions) - 1:
        raise BridgeError("Stage 4C revision history is inconsistent.")
    for i, entry in enumerate(versions):
        if not isinstance(entry, dict) or entry.get("version") != i:
            raise BridgeError("Stage 4C version ordering is invalid.")
        for key, suffix in (("draft_path", "draft.md"), ("review_path", "review.json")):
            required = f"evidence/{prefix_name}_v{i}_{suffix}"
            if entry.get(key) != required:
                raise BridgeError("Stage 4C file reference differs from the expected evidence path.")
    entry = versions[-1]
    draft_path = evidence / f"{prefix_name}_v{len(versions)-1}_draft.md"
    review_path = evidence / f"{prefix_name}_v{len(versions)-1}_review.json"
    try:
        if draft_path.stat().st_size > _MAX_REPORT_BYTES or review_path.stat().st_size > _MAX_REPORT_BYTES:
            raise BridgeError("Stage 4C report exceeds the size limit.")
        markdown = draft_path.read_text(encoding="utf-8")
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
        raise BridgeError("Stage 4C reviewed files are missing or unreadable.") from exc
    sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    if not markdown.strip() or not isinstance(review, dict) or not (
        entry.get("draft_sha256") == sha
        and review.get("draft_sha256") == sha
        and review.get("source_thread_id") == tid
        and review.get("critic_review_performed") is True
        and review.get("human_report_approved") is False
        and review.get("report_submitted_for_review") is False
        and review.get("publication_performed") is False
        and review.get("semantic_entailment_checked") is False
    ):
        raise BridgeError("Stage 4C draft/critic integrity or approval binding failed.")
    findings = review.get("findings")
    blockers = review.get("hard_blockers")
    if not isinstance(findings, list) or not findings or not isinstance(blockers, list):
        raise BridgeError("Stage 4C Critic findings or blockers are missing.")
    if any(not isinstance(f, dict) or f.get("verdict") not in
           {"SUPPORTED", "UNSUPPORTED", "UNCERTAIN", "NOT_REVIEWED"} for f in findings):
        raise BridgeError("Stage 4C Critic returned unexpected verdicts.")
    if type(review.get("claim_count")) is not int or review["claim_count"] != len(findings):
        raise BridgeError("Stage 4C Critic claim count does not match its findings.")
    supported = sum(f["verdict"] == "SUPPORTED" for f in findings)
    ready = (
        manifest["phase"] == "STAGE4C_READY_FOR_HUMAN_REVIEW"
        and review.get("model_semantic_assessment_performed") is True
        and not blockers
        and supported == len(findings)
    )
    return {
        "thread_id": tid,
        "phase": manifest["phase"],
        "ready_for_human_review": ready,
        "human_report_approved": False,
        "publication_performed": False,
        "revision_count": manifest["revision_count"],
        "supported": supported,
        "claim_count": len(findings),
        "hard_blockers": blockers,
        "draft_sha256": sha,
        "draft_markdown": markdown,
        "critic_review": review,
        "manifest_name": manifest_path.name,
    }


async def _find_running_api() -> tuple[str, str, str]:
    lookup = [
        "docker", "ps", "--filter", f"label=com.docker.compose.project={DOCKER_PROJECT}",
        "--filter", f"label=com.docker.compose.service={DOCKER_SERVICE}",
        "--format", "{{.ID}}",
    ]
    cid = select_container_id(await _run_docker(lookup, timeout=20))
    image_id = (await _run_docker([
        "docker", "inspect", "--format", "{{.Image}}", cid,
    ], timeout=20)).decode("ascii").strip()
    if _IMAGE_RE.fullmatch(image_id) is None:
        raise BridgeError("Unable to verify the active API container image.")
    release = (await _run_docker([
        "docker", "exec", "-i", cid, "python", "-c",
        "import os; print(os.getenv('ANALYSTDESK_VERIFIED_RELEASE_ID',''))",
    ], timeout=30)).decode("ascii").strip()
    if _RELEASE_RE.fullmatch(release) is None:
        raise BridgeError("Docker API has no valid verified release configured.")
    return cid, image_id, release


def _safe_stage4c_error(stdout: bytes, exit_code: int) -> str:
    """Read only the CLI's intentionally safe error JSON, never Docker stderr.

    stage4c3_cli.main catches exceptions and emits {status: ERROR, error_type,
    message}. Non-ResearchError messages are already suppressed by that CLI.
    """
    generic = f"Stage 4C CLI failed (Docker exit {exit_code}); no structured diagnostic returned."
    try:
        if len(stdout) > 16_384:
            return generic
        payload = json.loads(stdout.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        return generic
    if not isinstance(payload, dict) or payload.get("status") != "ERROR":
        return generic
    error_type = payload.get("error_type")
    message = payload.get("message")
    if not (isinstance(error_type, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error_type)):
        return generic
    if not isinstance(message, str) or len(message) > 2000:
        return f"Stage 4C CLI error: {error_type}."
    # Model/provider diagnostic strings can occasionally contain credentials;
    # suppress token-like substrings rather than logging raw stdout/stderr.
    message = re.sub(r"(?i)sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", message)
    message = re.sub(
        r"(?i)(?:api[_ -]?key|authorization|bearer|token)\s*(?:=|:)\s*[^\s,;]+",
        "[REDACTED]", message,
    )
    message = " ".join(message.split())[:350]
    return f"Stage 4C CLI error ({error_type}): {message}"


async def _run_review_cli(cmd: list[str], *, timeout: int) -> bytes:
    """Execute Docker review with bounded stdout; preserve safe CLI errors.

    Ordinary Phase 10 Docker commands retain their existing sealed errors.
    Docker stderr is deliberately never surfaced to Chainlit.
    """
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
            raise BridgeError("Stage 4C review timed out; no review was accepted.") from None
    except FileNotFoundError as exc:
        raise BridgeError("Docker executable not found in the Chainlit environment.") from exc
    except OSError as exc:
        raise BridgeError("Unable to start the Stage 4C Docker review job.") from exc
    if proc.returncode != 0:
        raise BridgeError(_safe_stage4c_error(stdout, proc.returncode))
    if len(stdout) > 500_000:
        raise BridgeError("Stage 4C completion response exceeds permitted size.")
    return stdout


async def run_live_review(thread_id: str) -> dict:
    """Run Writer/Critic under the API image with the *same* Docker checkpoints.

    The temporary job only gets read access to the local .env for OpenRouter.
    It writes evidence on the host, removes itself, never invokes Stage 4C-4.
    """
    tid = check_thread_id(thread_id)
    if _REVIEW_LOCK.locked():
        raise BridgeError("Another Stage 4C review is running; retry after it finishes.")
    async with _REVIEW_LOCK:
        if not (ROOT / ".env").is_file():
            raise BridgeError("Local .env is missing. The live Writer/Critic needs an OpenRouter key.")
        evidence = ROOT / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        cid, image_id, release = await _find_running_api()
        prefix_name = f"ui_stage4c3_{tid}_{uuid.uuid4().hex[:8]}"
        job_name = f"analystdesk-review-{uuid.uuid4().hex[:16]}"
        cmd = [
            "docker", "run", "--rm", "--init", "--name", job_name,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--volumes-from", cid,
            "--mount", f"type=bind,source={evidence},target=/app/evidence",
            "--mount", f"type=bind,source={ROOT / '.env'},target=/app/.env,readonly",
            "--env", f"ANALYSTDESK_VERIFIED_RELEASE_ID={release}",
            image_id,
            "python", "-m", "analyst_desk.stage4c3_cli", "run",
            "--thread-id", tid,
            "--prefix", f"evidence/{prefix_name}",
            "--max-revisions", "2",
        ]
        try:
            stdout = await _run_review_cli(cmd, timeout=1200)
        except BridgeError as exc:
            # docker run --rm normally removes itself; force cleanup after timeouts.
            try:
                await _run_docker(["docker", "rm", "-f", job_name], timeout=30)
            except BridgeError:
                pass
            raise BridgeError(
                f"Live Stage 4C review failed: {exc} "
                "The existing research and offline drafts remain unchanged."
            ) from exc
        try:
            result = json.loads(stdout.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise BridgeError("Stage 4C review returned unreadable completion metadata.") from exc
        if not isinstance(result, dict) or result.get("status") != "PASS" or result.get("thread_id") != tid:
            raise BridgeError("Stage 4C review did not return a verified completion.")
        return validate_review_bundle(ROOT, tid, prefix_name)

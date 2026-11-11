"""AnalystDesk Phase 6A-2: isolated, read-only model/transport diagnostics.

Requires the project's activated environment. This script never prints keys,
provider response bodies, request text, or raw exception messages.
"""
from __future__ import annotations

import os
from pathlib import Path

# Resolve the same project .env as the application when run from its root.
from dotenv import dotenv_values, load_dotenv

project_env = Path.cwd() / '.env'
values = dotenv_values(project_env) if project_env.is_file() else {}
load_dotenv(project_env, override=False)

print('=== Configuration ===', flush=True)
configured_nvidia_key = (values.get('NVIDIA_API_KEY') or '').strip()
effective_nvidia_key = os.getenv('NVIDIA_API_KEY', '').strip()
print(f'nvidia_key_in_dotenv={bool(configured_nvidia_key)}', flush=True)
print(f'nvidia_effective_key_present={bool(effective_nvidia_key)}', flush=True)
print(f'nvidia_effective_key_matches_dotenv={bool(configured_nvidia_key) and effective_nvidia_key == configured_nvidia_key}', flush=True)
print(f'https_proxy_configured={bool(os.getenv("HTTPS_PROXY") or os.getenv("https_proxy"))}', flush=True)

print('=== Local Prompt Guard 2 ===', flush=True)
try:
    from analyst_desk.phase6a_models import PromptGuard2CPU, GuardModelError
    guard = PromptGuard2CPU()
    pipeline = guard._load()
    config = getattr(getattr(pipeline, 'model', None), 'config', None)
    labels = getattr(config, 'id2label', None)
    print('prompt_guard_model_loaded=True', flush=True)
    if isinstance(labels, dict):
        print('prompt_guard_model_labels=' + ','.join(str(v) for v in labels.values()), flush=True)
    else:
        print('prompt_guard_model_labels=unavailable', flush=True)
    sample = 'Compare Microsoft and Alphabet annual SEC filings and revenue risks.'
    output = pipeline(sample, top_k=None, truncation=True, max_length=512)
    if isinstance(output, list) and len(output) == 1 and isinstance(output[0], list):
        output = output[0]
    if isinstance(output, list):
        print('prompt_guard_returned_labels=' + ','.join(str(item.get('label', 'missing')) for item in output if isinstance(item, dict)), flush=True)
        print('prompt_guard_class_count=' + str(len(output)), flush=True)
    else:
        print('prompt_guard_output_shape=' + type(output).__name__, flush=True)
    score = guard(sample)
    print('prompt_guard_adapter_result=PASS', flush=True)
    print(f'prompt_guard_malicious_score={score:.6f}', flush=True)
except Exception as exc:
    print('prompt_guard_adapter_result=ERROR', flush=True)
    print('prompt_guard_exception_type=' + type(exc).__name__, flush=True)
    # GuardModelError text is locally authored; never log raw provider exceptions.
    try:
        if isinstance(exc, GuardModelError):
            print('prompt_guard_adapter_reason=' + str(exc), flush=True)
    except NameError:
        pass

print('=== NVIDIA HTTPS connectivity (no model inference) ===', flush=True)
try:
    import httpx
    if not effective_nvidia_key:
        print('nvidia_transport_result=KEY_MISSING', flush=True)
    else:
        resp = httpx.get(
            'https://integrate.api.nvidia.com/v1/models',
            headers={'Authorization': 'Bearer ' + effective_nvidia_key},
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=False,
        )
        print('nvidia_transport_result=HTTP_RESPONSE', flush=True)
        print('nvidia_http_status=' + str(resp.status_code), flush=True)
        # Do not print response content or sensitive headers.
except Exception as exc:
    print('nvidia_transport_result=ERROR', flush=True)
    print('nvidia_transport_exception_type=' + type(exc).__name__, flush=True)
    cause = getattr(exc, '__cause__', None)
    if cause is not None:
        print('nvidia_transport_cause_type=' + type(cause).__name__, flush=True)

"""Read-only Phase 6A-2 provider diagnostics; never prints tokens, raw prompts,
provider response text, URL parameters, or exception messages.
Place in AnalystDesk project root and run with its activated Python environment.
"""
from __future__ import annotations

import os
from pathlib import Path

CLEAN = 'Compare MSFT and GOOGL annual SEC filings and revenue risks.'


def show_error(provider: str, error: BaseException) -> None:
    print(f'{provider}.result=ERROR')
    print(f'{provider}.exception_type={type(error).__name__}')
    visited = set()
    current = error
    for depth in range(5):
        if id(current) in visited:
            break
        visited.add(id(current))
        code = getattr(current, 'status_code', None)
        response = getattr(current, 'response', None)
        if code is None and response is not None:
            code = getattr(response, 'status_code', None)
        if type(code) is int:
            print(f'{provider}.http_status={code}')
            break
        current = getattr(current, '__cause__', None) or getattr(current, '__context__', None)
        if current is None:
            break
    if provider == 'prompt_guard':
        print('prompt_guard.hint=Check Hugging Face model license/access, local authentication, or import/model-loading dependencies.')
    elif provider == 'nvidia':
        print('nvidia.hint=401/403: API key or entitlement; 404: model access; 429: quota; 5xx: provider error; no HTTP code: local parser/SDK issue.')


def run() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / '.env', override=False)
    except Exception as error:
        show_error('dotenv', error)
        return

    print('=== PROMPT GUARD 2: local 86M classifier ===')
    try:
        from huggingface_hub import get_token
        print(f'huggingface_token_present={bool(get_token())}')
    except Exception as error:
        show_error('huggingface_auth', error)
    try:
        from analyst_desk.phase6a_models import PromptGuard2CPU
        score = PromptGuard2CPU()(CLEAN)
        print('prompt_guard.result=PASS')
        print(f'prompt_guard.malicious_probability={score:.6f}')
    except Exception as error:
        show_error('prompt_guard', error)

    print('=== NVIDIA LLAMA GUARD 4: hosted safety classifier ===')
    key = os.getenv('NVIDIA_API_KEY', '').strip()
    print(f'nvidia_key_present={bool(key)}')
    if not key:
        print('nvidia.result=NOT_CONFIGURED')
        return
    try:
        from openai import OpenAI
        from analyst_desk.phase6a_models import LLAMA_GUARD_MODEL, llama_guard_verdict
        from types import SimpleNamespace
        client = OpenAI(api_key=key, base_url='https://integrate.api.nvidia.com/v1', timeout=40, max_retries=0)
        response = client.chat.completions.create(
            model=LLAMA_GUARD_MODEL,
            messages=[{'role': 'user', 'content': CLEAN}],
            max_tokens=30,
        )
        text = response.choices[0].message.content if response.choices else None
        if not isinstance(text, str):
            print('nvidia.result=ERROR')
            print('nvidia.response_shape=non_text')
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        first_line = lines[0] if lines else ''
        print(f'nvidia.response_first_line_category={first_line if first_line in ("safe", "unsafe") else "unexpected"}')
        print(f'nvidia.response_line_count={len(lines)}')
        mock = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=text))]))))
        verdict = llama_guard_verdict(CLEAN, client=mock)
        print('nvidia.result=PASS')
        print(f'nvidia.safe={verdict["safe"]}')
    except Exception as error:
        show_error('nvidia', error)


if __name__ == '__main__':
    run()

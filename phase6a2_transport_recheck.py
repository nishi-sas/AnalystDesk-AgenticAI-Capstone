"""Read-only TLS/model-access and NVIDIA timeout diagnostic for AnalystDesk.

Prints only safe statuses, classifications and exception types/status codes.
No tokens, prompts, URLs carrying secrets or raw exception messages logged.
"""
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env', override=False)


def safe_error(prefix: str, exc: BaseException) -> None:
    print(f'{prefix}.status=ERROR')
    print(f'{prefix}.exception_type={type(exc).__name__}')
    seen = set()
    cur: BaseException | None = exc
    for _ in range(6):
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        code = getattr(cur, 'status_code', None)
        response = getattr(cur, 'response', None)
        if code is None and response is not None:
            code = getattr(response, 'status_code', None)
        if isinstance(code, int):
            print(f'{prefix}.http_status={code}')
            break
        cur = getattr(cur, '__cause__', None) or getattr(cur, '__context__', None)


print('== HTTPS trust check ==')
try:
    import requests
    response = requests.get('https://huggingface.co/', timeout=20)
    print(f'huggingface_tls=PASS')  # Successful verified handshake, even if HTTP status is non-200
    print(f'huggingface_home_http={response.status_code}')
except Exception as exc:
    safe_error('huggingface_tls', exc)

print('== Model access check ==')
try:
    from huggingface_hub import hf_hub_download
    config_file = hf_hub_download('meta-llama/Llama-Prompt-Guard-2-86M', 'config.json', local_files_only=False)
    print('prompt_guard_config=PASS')
except Exception as exc:
    safe_error('prompt_guard_config', exc)

print('== NVIDIA one-call timeout probe (120 seconds) ==')
key = os.getenv('NVIDIA_API_KEY', '').strip()
if not key:
    print('nvidia.status=NOT_CONFIGURED')
else:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url='https://integrate.api.nvidia.com/v1', timeout=120, max_retries=0)
        completion = client.chat.completions.create(
            model='meta/llama-guard-4-12b',
            messages=[{'role': 'user', 'content': 'Compare Microsoft and Alphabet annual SEC filings.'}],
            max_tokens=10,
        )
        content = completion.choices[0].message.content if completion.choices else None
        first = content.strip().splitlines()[0].strip() if isinstance(content, str) and content.strip() else ''
        print(f'nvidia.status={"PASS" if first in ("safe", "unsafe") else "UNEXPECTED_VERDICT"}')
        print(f'nvidia.first_line_category={first if first in ("safe", "unsafe") else "unexpected"}')
    except Exception as exc:
        safe_error('nvidia', exc)

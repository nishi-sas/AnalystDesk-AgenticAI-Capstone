"""Phase 6A-1 input boundary: deterministic controls + explicit optional ML adapters.

This is not a replacement for Prompt Guard 2 or Llama Guard 4. Model checks are
reported as NOT_CONFIGURED until adapters are connected and validated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Callable


class InputGuardrailError(ValueError):
    """Malformed policy call or unsafe input data."""


@dataclass(frozen=True)
class InputDecision:
    passed: bool
    checks: tuple[dict[str, Any], ...]
    external_data: dict[str, Any] | None

    @property
    def block_codes(self) -> tuple[str, ...]:
        return tuple(c['code'] for c in self.checks if c['status'] == 'BLOCK')

    def receipt(self) -> dict[str, Any]:
        """Non-sensitive audit receipt: do not include request or raw external text."""
        return {'passed': self.passed, 'block_codes': list(self.block_codes),
                'checks': [dict(c) for c in self.checks],
                'external_content_tagged': self.external_data is not None}


# Limited, high-precision signatures; not a complete prompt injection detector.
_INSTRUCTION_HIJACK = (
    re.compile(r'\b(?:ignore|disregard|override|bypass)\b.{0,45}\b(?:previous|prior|system|developer|safety)\b.{0,40}\b(?:instructions?|prompts?|rules?|polic(?:y|ies))\b', re.I | re.S),
    re.compile(r'\b(?:reveal|print|dump|exfiltrate|send)\b.{0,50}\b(?:api[_ -]?keys?|passwords?|secret(?:s)?|system[_ -]?prompts?|environment[_ -]?variables?)\b', re.I | re.S),
    re.compile(r'\b(?:pretend|act as|you are now)\b.{0,35}\b(?:system|developer|administrator|root)\b', re.I | re.S),
    re.compile(r'\b(?:execute|run)\b.{0,25}\b(?:shell|powershell|terminal|cmd\.exe|subprocess)\b', re.I | re.S),
)
_INVESTMENT_REQUESTS = (
    re.compile(r'\b(?:should\s+i|shall\s+i|do\s+you\s+recommend\s+that\s+i)\s+(?:buy|sell|short)\b', re.I),
    re.compile(r'\b(?:give\s+me|provide)\s+(?:a\s+)?(?:stock\s+tips?|buy\s+recommendation|sell\s+recommendation|target\s+price)\b', re.I),
)
_FINANCE_CONTEXT = re.compile(
    r'\b(?:10[- ]?k|filings?|revenue|earnings|income|operating\s+margin|financial|'
    r'risks?|risk\s+factors?|disclosures?|sec|xbrl|compar(?:e|ison|ative)|'
    r'annual\s+report|research|analy[sz]e|performance|cash\s+flow|cybersecurity|'
    r'ip\s+litigation|regulation|fiscal)\b', re.I
)
_TICKER_RE = re.compile(r'\b[A-Za-z][A-Za-z0-9]{1,20}\b')
_ALIAS = {'microsoft': 'MSFT', 'msft': 'MSFT', 'alphabet': 'GOOGL', 'google': 'GOOGL', 'googl': 'GOOGL'}
_ANALYST = re.compile(r'[A-Za-z0-9_-]{3,64}\Z')


def _check(code: str, passed: bool, *, status: str | None = None) -> dict[str, Any]:
    return {'code': code, 'status': status or ('PASS' if passed else 'BLOCK')}


def _optional_classifier(name: str, callback: Callable[[str], Any] | None, request: str,
                         expected: str) -> dict[str, Any]:
    if callback is None:
        return _check(name, True, status='NOT_CONFIGURED')
    try:
        value = callback(request)
        if expected == 'scope':
            good = isinstance(value, dict) and type(value.get('in_scope')) is bool and value['in_scope']
        elif expected == 'score':
            good = type(value) in (float, int) and 0 <= value <= 1 and value < 0.5
        elif expected == 'safe':
            good = (type(value) is bool and value) or (isinstance(value, dict) and type(value.get('safe')) is bool and value['safe'])
        else:
            raise InputGuardrailError('Unknown classifier schema')
        return _check(name, bool(good))
    except Exception:
        # Do not echo model exceptions: they may contain external content or credentials.
        return _check(name + '_ERROR', False)


def tag_untrusted_external_content(value: str | None) -> dict[str, Any] | None:
    """Label supplied excerpt data without granting it any instruction authority."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 20_000 or '\x00' in value:
        raise InputGuardrailError('External content must be bounded UTF-8 text without NUL')
    return {'trust_level': 'UNTRUSTED_DATA', 'source_kind': 'USER_SUPPLIED_EXTERNAL_TEXT',
            'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest(), 'text': value}


def run_input_guardrails(
    request: str,
    analyst_id: str,
    *,
    allowed_tickers: tuple[str, ...] = ('MSFT', 'GOOGL'),
    external_text: str | None = None,
    scope_classifier: Callable[[str], Any] | None = None,
    injection_classifier: Callable[[str], Any] | None = None,
    safety_classifier: Callable[[str], Any] | None = None,
    require_model_checks: bool = False,
) -> InputDecision:
    """Fail-closed on malformed inputs; don't pretend optional classifiers ran."""
    if not isinstance(request, str) or not isinstance(analyst_id, str):
        raise InputGuardrailError('request and analyst_id must be strings')
    if not isinstance(allowed_tickers, tuple) or not allowed_tickers or not all(
        isinstance(t, str) and re.fullmatch('[A-Z]{2,6}', t) for t in allowed_tickers
    ):
        raise InputGuardrailError('Invalid allowed_tickers policy')
    checks: list[dict[str, Any]] = []
    bounded = 10 <= len(request.strip()) <= 1200 and not any(
        ord(c) < 32 and c not in '\n\t\r' for c in request
    )
    checks.append(_check('REQUEST_BOUNDS', bounded))
    checks.append(_check('ANALYST_ID', bool(_ANALYST.fullmatch(analyst_id))))
    mentioned: set[str] = set()
    for m in _TICKER_RE.finditer(request):
        token = m.group(0)
        t = _ALIAS.get(token.lower(), token if token.isupper() else '')
        if t in allowed_tickers:
            mentioned.add(t)
    checks.append(_check('ALLOWED_COMPANY_SCOPE', bool(mentioned)))
    checks.append(_check('FINANCIAL_RESEARCH_SCOPE', bool(_FINANCE_CONTEXT.search(request))))
    checks.append(_check('DIRECT_PROMPT_INJECTION', not any(p.search(request) for p in _INSTRUCTION_HIJACK)))
    checks.append(_check('DIRECT_INVESTMENT_ADVICE_REQUEST', not any(p.search(request) for p in _INVESTMENT_REQUESTS)))
    for name, callback, contract in (
        ('SCOPE_MODEL', scope_classifier, 'scope'),
        ('INJECTION_MODEL', injection_classifier, 'score'),
        ('SAFETY_MODEL', safety_classifier, 'safe'),
    ):
        result = _optional_classifier(name, callback, request, contract)
        if require_model_checks and result['status'] == 'NOT_CONFIGURED':
            result = _check(name + '_REQUIRED', False)
        checks.append(result)
    try:
        tagged = tag_untrusted_external_content(external_text)
        checks.append(_check('EXTERNAL_CONTENT_ENVELOPE', True))
    except InputGuardrailError:
        tagged = None
        checks.append(_check('EXTERNAL_CONTENT_ENVELOPE', False))
    return InputDecision(not any(c['status'] == 'BLOCK' for c in checks), tuple(checks), tagged)

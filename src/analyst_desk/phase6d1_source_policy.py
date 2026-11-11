"""High-confidence untrusted SEC/source prompt-injection quarantine.

This policy is intentionally limited to explicit control-plane instructions. It
is not a general NLP detection system and does not establish semantic fidelity.
No content or credentials are included in error messages or audit receipts.
"""
from __future__ import annotations
import re

_RULES = (
    ('ROLE_SPOOFING', re.compile(r'(?:<\|im_start\|>|\[\s*(?:system|developer|assistant|tool)\s*\]|^\s*(?:system|developer)\s*:\s*|^\s*#{1,4}\s*(?:system|developer)\s*$)', re.I | re.M)),
    ('INSTRUCTION_OVERRIDE', re.compile(r'\b(?:ignore|disregard|override|forget|bypass)\s+(?:(?:all|any|the|your|earlier|above|previous|prior|system|developer|safety|security)\s+){0,5}(?:instructions?|prompts?|rules?|polic(?:y|ies)|guardrails?)\b', re.I)),
    ('CONTROL_PLANE_ACTION', re.compile(r'\b(?:approve|sign|publish|mark|set|submit)\b.{0,65}\b(?:report|draft|approval|approved|published|review|signature|state)\b|\b(?:human\s+approval\s+(?:is\s+)?(?:granted|not\s+required)|bypass\s+(?:human\s+)?review)\b', re.I | re.S)),
    ('SECRET_EXFILTRATION', re.compile(r'\b(?:send|post|transmit|exfiltrat\w*|upload|leak|disclose|print)\b.{0,90}\b(?:secret\w*|tokens?|watchlists?|api\s*keys?|credentials?|private\s*keys?)\b|\b(?:OPENROUTER_API_KEY|NVIDIA_API_KEY|HF_TOKEN|AWS_SECRET_ACCESS_KEY)\s*=', re.I | re.S)),
    ('TOOL_CALL_INJECTION', re.compile(r'\b(?:call|invoke|execute|run)\s+(?:the\s+)?(?:shell|terminal|python|exec(?:ute_code)?|mcp\s+tool|publish_report|create_report_draft)\b', re.I)),
    ('OUTPUT_CONTAMINATION', re.compile(r'\b(?:insert|append|include|write|print)\b.{0,45}\b(?:in|into|to)\b.{0,40}\b(?:report|summary|response|answer|executive summary)\b', re.I | re.S)),
    ('ACTIVE_PAYLOAD', re.compile(r'<\s*(?:script|iframe|img)\b|javascript\s*:|!\[[^\]]*\]\(https?://|\[[^\]]*\]\(https?://(?!www\.sec\.gov/Archives/)', re.I)),
    ('INVESTMENT_INSTRUCTION', re.compile(r'\b(?:we\s+recommend\s+(?:buying|selling)|investors?\s+should\s+(?:buy|sell)|strong\s+buy|price\s+target)\b', re.I)),
)


def source_injection_codes(text: str, *, narrative: bool = False) -> tuple[str, ...]:
    """Identify explicit instructions in untrusted data; no raw text in return.

    Model-generated comparison narrative may contain escaped HTML used for a
    safe Markdown test; active-markup quarantine there is handled by Writer's
    HTML escaping and the Phase 6B report gate, rather than this source rule.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 500_000:
        return ('SOURCE_TEXT_INVALID',)
    return tuple(name for name, rx in _RULES if (not narrative or name != 'ACTIVE_PAYLOAD') and rx.search(text))


def require_untrusted_source_safe(text: str, *, narrative: bool = False) -> None:
    codes = source_injection_codes(text, narrative=narrative)
    if codes:
        from .stage4b_research import ResearchError
        # No user-supplied passages in exceptions/logs.
        raise ResearchError('UNTRUSTED_SOURCE_INJECTION_QUARANTINED: ' + ','.join(codes))

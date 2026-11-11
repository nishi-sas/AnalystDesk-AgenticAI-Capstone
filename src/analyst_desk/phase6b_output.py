"""Phase 6B-1: read-only post-generation / pre-portal report and tool policy.

This is a deterministic policy boundary, not a semantic entailment verifier.
The upstream SEC audit/critic, portal revision hash and signed human review
remain independent mandatory controls. No secrets or report bodies in receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Callable

from .stage4a_permissions import assert_tool_permission

_PASSAGE = re.compile(r'[A-Z]{1,10}_\d{4}-\d{2}-\d{2}_Item(?:1A|7|8)_\d{5}\Z')
_FACT = re.compile(r'CIK\d{10}\|\d{10}-\d{2}-\d{6}\|us-gaap:[A-Za-z][A-Za-z0-9]*\|\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}\|USD\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[0-9a-f]{32}\Z')
_ADVICE = (
    re.compile(r'\b(?:strong\s+buy|buy\s+(?:shares|stocks?|MSFT|GOOGL)|sell\s+(?:shares|stocks?|MSFT|GOOGL))\b', re.I),
    re.compile(r'\b(?:price\s+target|target\s+price|guaranteed\s+(?:returns?|profits?)|will\s+outperform)\b', re.I),
    re.compile(r'\b(?:we\s+recommend\s+(?:buying|selling)|investors?\s+should\s+(?:buy|sell))\b', re.I),
)
_LEAK = (
    re.compile(r'\b(?:nvapi-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', re.I),
    re.compile(r'(?im)^\s*(?:OPENROUTER_API_KEY|NVIDIA_API_KEY|HF_TOKEN|AWS_SECRET_ACCESS_KEY)\s*='),
)
_ACTIVE_MARKUP = re.compile(r'<\s*/?\s*(?:script|iframe|object|embed|img|form|meta|style|link|svg)\b|javascript\s*:|data\s*:\s*text/html', re.I)
_MARKDOWN_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
_OUTBOUND_URL = re.compile(r'https?://([^/\s)<>]+)(/[^\s)<>]*)?', re.I)
_INSTRUCTION = re.compile(r'\b(?:ignore|override|disregard)\s+(?:all\s+)?(?:previous|prior|system|developer)\s+(?:instructions?|prompts?|rules?)\b', re.I)
_FINANCIAL_ROW = re.compile(r'^\|\s*([A-Z]{2,10})\s*\|.*\d+(?:\.\d+)?\s*%.*\|\s*$', re.M)


class OutputGuardrailError(ValueError):
    """A malformed guardrail invocation; never logs raw user/model text."""


@dataclass(frozen=True)
class OutputDecision:
    passed: bool
    checks: tuple[dict[str, str], ...]

    @property
    def block_codes(self) -> tuple[str, ...]:
        return tuple(x['code'] for x in self.checks if x['status'] == 'BLOCK')

    def receipt(self) -> dict[str, Any]:
        return {'passed': self.passed, 'block_codes': list(self.block_codes),
                'checks': [dict(x) for x in self.checks]}


def _check(code: str, ok: bool, status: str | None = None) -> dict[str, str]:
    return {'code': code, 'status': status or ('PASS' if ok else 'BLOCK')}


# Fixed issuer identities for the verified 12-company SEC corpus.
# Only the presence of company-matched revenue operands is checked here.
# Phase 6D2 separately recomputes percentages from SEC-verified XBRL.
_SUPPORTED_CIK_PREFIXES = {
    'AAPL': 'CIK0000320193|',
    'ADBE': 'CIK0000796343|',
    'BBY': 'CIK0000764478|',
    'CRM': 'CIK0001108524|',
    'DG': 'CIK0000029534|',
    'GOOGL': 'CIK0001652044|',
    'HD': 'CIK0000354950|',
    'LOW': 'CIK0000060667|',
    'META': 'CIK0001326801|',
    'MSFT': 'CIK0000789019|',
    'TGT': 'CIK0000027419|',
    'ULTA': 'CIK0001403568|',
}

def run_output_guardrails(bundle: dict[str, Any], *,
                          safety_classifier: Callable[[str], Any] | None = None,
                          require_model_checks: bool = False) -> OutputDecision:
    """Fail closed on unsafe Markdown before an MCP portal write.

    A check named NUMERIC_FACT_PROVENANCE verifies source *presence and company*
    only; it does NOT independently establish that the number is correct.
    """
    if not isinstance(bundle, dict):
        raise OutputGuardrailError('Output bundle must be an object')
    text = bundle.get('markdown')
    if not isinstance(text, str) or not (20 <= len(text) <= 180_000) or '\x00' in text:
        raise OutputGuardrailError('Output Markdown must be bounded UTF-8 text')
    ids = bundle.get('source_ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(x, str) for x in ids):
        raise OutputGuardrailError('Output sources must be a bounded list')
    sha = bundle.get('sha256')
    review = bundle.get('review')
    if not isinstance(review, dict) or not isinstance(sha, str):
        raise OutputGuardrailError('Output requires a linked critic review and SHA-256')
    actual = hashlib.sha256(text.encode('utf-8')).hexdigest()
    valid_sha = bool(_SHA.fullmatch(sha)) and actual == sha and review.get('draft_sha256') == sha
    valid_ids = len(ids) == len(set(ids)) and all(_PASSAGE.fullmatch(x) or _FACT.fullmatch(x) for x in ids)
    cited = valid_ids and all('`' + x + '`' in text for x in ids)
    facts = {i for i in ids if _FACT.fullmatch(i)}
    checks = [
        _check('OUTPUT_SHA256_BINDING', valid_sha),
        _check('SEC_CITATION_IDENTITIES', bool(valid_ids and cited and facts)),
        _check('NO_INVESTMENT_ADVICE', not any(p.search(text) for p in _ADVICE)),
        _check('NO_SECRET_DISCLOSURE', not any(p.search(text) for p in _LEAK)),
        _check('NO_ACTIVE_OR_REMOTE_CONTENT', not _ACTIVE_MARKUP.search(text)
               and not _MARKDOWN_IMAGE.search(text)
               and all(host.lower() == 'www.sec.gov' and (path or '').startswith('/Archives/')
                       for host, path in _OUTBOUND_URL.findall(text))),
        _check('NO_INSTRUCTION_HIJACK_IN_REPORT', not _INSTRUCTION.search(text)),
    ]
    # Extract *reported percentages*, not incidental years in dates/citation IDs.
    # Require at least one tagged revenue fact for each company shown in a %-row.
    # More comprehensive fact-value reconciliation is upstream in Stage 4B/4C.
    numeric_rows = list(_FINANCIAL_ROW.finditer(text))
    numeric_ok = True
    for row in numeric_rows:
        ticker = row.group(1)
        cik = _SUPPORTED_CIK_PREFIXES.get(ticker)
        if cik is None or not any(x.startswith(cik) and ('|us-gaap:Revenues|' in x or
                '|us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax|' in x) for x in facts):
            numeric_ok = False
    # For other percentages in narrative, manual assertion is required unless
    # they occur within a source-tagged or metric section; forbid unstructured %.
    lines = text.splitlines()
    if any('%' in line and not line.lstrip().startswith('|') and
           not ('`CIK' in line and '|us-gaap:' in line) for line in lines):
        numeric_ok = False
    checks.append(_check('NUMERIC_FACT_PROVENANCE', numeric_ok))
    findings = review.get('findings')
    reviewed = review.get('critic_review_performed') is True and review.get('human_report_approved') is False and \
        review.get('publication_performed') is False and isinstance(findings, list) and 4 <= len(findings) <= 5
    checks.append(_check('REVIEW_NOT_SELF_APPROVED', reviewed))
    if safety_classifier is None:
        checks.append(_check('OUTPUT_SAFETY_MODEL_REQUIRED', False) if require_model_checks else
                      _check('OUTPUT_SAFETY_MODEL', True, 'NOT_CONFIGURED'))
    else:
        try:
            # Do not silently truncate and then call the result a whole-report verdict.
            if len(text) > 12_000:
                raise OutputGuardrailError('Model input exceeds whole-report budget')
            verdict = safety_classifier(text)
            safe = isinstance(verdict, dict) and set(verdict) == {'safe'} and type(verdict['safe']) is bool
            checks.append(_check('OUTPUT_SAFETY_MODEL', safe and verdict['safe']))
        except Exception:
            checks.append(_check('OUTPUT_SAFETY_MODEL_ERROR', False))
    return OutputDecision(not any(c['status'] == 'BLOCK' for c in checks), tuple(checks))


def assert_portal_tool_arguments(role: str, tool_name: str, args: Any) -> None:
    """Additional argument boundary for the high-impact PortalMCPGateway tools.

    Role checks remain mandatory and enforced again in the existing gateway.
    This does not replace the portal's revision/signature verification.
    """
    assert_tool_permission(role, tool_name)
    if not isinstance(args, dict):
        raise OutputGuardrailError('Tool arguments must be an object')
    schemas = {
        'create_report_draft': ({'title', 'markdown', 'source_ids'}, {'open_blockers'}),
        'get_report': ({'report_id'}, set()),
        'submit_for_review': ({'report_id', 'expected_revision'}, set()),
        'publish_report': ({'report_id', 'expected_sha256'}, set()),
    }
    if tool_name not in schemas:
        raise OutputGuardrailError('Tool is not on this portal gateway')
    required, optional = schemas[tool_name]
    if not required.issubset(args) or not set(args).issubset(required | optional):
        raise OutputGuardrailError('Tool argument names do not match approved schema')
    if 'report_id' in args and (not isinstance(args['report_id'], str) or not _ID.fullmatch(args['report_id'])):
        raise OutputGuardrailError('Invalid report identifier')
    if 'expected_revision' in args and (type(args['expected_revision']) is not int or not 1 <= args['expected_revision'] <= 10_000):
        raise OutputGuardrailError('Invalid report revision')
    if 'expected_sha256' in args and (not isinstance(args['expected_sha256'], str) or not _SHA.fullmatch(args['expected_sha256'])):
        raise OutputGuardrailError('Invalid report hash')
    if tool_name == 'create_report_draft':
        if not isinstance(args['title'], str) or not 1 <= len(args['title']) <= 200:
            raise OutputGuardrailError('Invalid title')
        if not isinstance(args['markdown'], str) or not 1 <= len(args['markdown']) <= 180_000:
            raise OutputGuardrailError('Invalid report body')
        sources = args['source_ids']
        if not isinstance(sources, list) or not 1 <= len(sources) <= 100 or any(
            not isinstance(x, str) or not (_PASSAGE.fullmatch(x) or _FACT.fullmatch(x)) for x in sources
        ):
            raise OutputGuardrailError('Invalid SEC source identifiers')
        blockers = args.get('open_blockers', [])
        if not isinstance(blockers, list) or any(not isinstance(x, str) or not 1 <= len(x) <= 500 for x in blockers):
            raise OutputGuardrailError('Invalid blocker inventory')

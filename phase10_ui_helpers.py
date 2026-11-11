"""Presentation-only helpers for the AnalystDesk Chainlit local UI.

No backend calls, project-file access, or approval decisions live here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SUPPORTED_TICKERS = (
    'AAPL', 'ADBE', 'BBY', 'CRM', 'DG', 'GOOGL',
    'HD', 'LOW', 'META', 'MSFT', 'TGT', 'ULTA',
)
FOCUS_OPTIONS = ('Financial and risks', 'Financial performance', 'Business risks')


@dataclass(frozen=True)
class FinancialRow:
    ticker: str
    report_date: str
    operating_margin: float
    revenue_growth_yoy: float
    classification: str


_ROW_RE = re.compile(
    r'^\|\s*([A-Z]{2,6})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|'
    r'\s*([+-]?\d+(?:\.\d+)?)%\s*\|\s*([+-]?\d+(?:\.\d+)?)%\s*\|'
    r'\s*([A-Z_]+)\s*\|\s*$',
    re.MULTILINE,
)


def validated_pair(company_a: str, company_b: str) -> tuple[str, str]:
    """Enforce the published UI cohort and distinct selection, not an access policy."""
    if company_a not in SUPPORTED_TICKERS or company_b not in SUPPORTED_TICKERS:
        raise ValueError('Select companies from the verified 12-company cohort.')
    if company_a == company_b:
        raise ValueError('Choose two different companies.')
    return company_a, company_b


def compose_research_request(question: str, company_a: str, company_b: str, focus: str) -> str:
    a, b = validated_pair(company_a, company_b)
    if focus not in FOCUS_OPTIONS:
        raise ValueError('Invalid analysis focus.')
    question = question.strip()
    if not question or len(question) > 6000:
        raise ValueError('Research question must contain 1–6000 characters.')
    return (
        f'Compare {a} and {b} using available SEC annual Form 10-K filings. '
        f'Analysis focus: {focus}. Research request: {question} '
        'Preserve the fiscal reporting periods, cite supporting evidence, '
        'and explicitly disclose analytical limitations.'
    )


def extract_financial_rows(markdown: str, expected_companies: tuple[str, ...]) -> list[FinancialRow]:
    """Display only rows actually present in a generated report; do not infer data."""
    if not isinstance(markdown, str):
        return []
    expected = set(expected_companies)
    found: dict[str, FinancialRow] = {}
    for match in _ROW_RE.finditer(markdown):
        ticker, report_date, margin, growth, classification = match.groups()
        if ticker not in expected or ticker in found:
            continue
        found[ticker] = FinancialRow(ticker, report_date, float(margin), float(growth), classification)
    return [found[t] for t in expected_companies if t in found]


def financial_table(rows: list[FinancialRow]) -> str:
    if not rows:
        return 'No structured financial comparison table is available in this draft.'
    lines = [
        '| Company | Fiscal year ended | Operating margin | Revenue growth YoY | Status |',
        '|---|---|---:|---:|---|',
    ]
    for r in rows:
        lines.append(
            f'| {r.ticker} | {r.report_date} | {r.operating_margin:.2f}% | '
            f'{r.revenue_growth_yoy:.2f}% | {r.classification} |'
        )
    return '\n'.join(lines)


def workflow_mermaid() -> str:
    return '''flowchart LR
    Q[Free-text research question] --> P[Stage 4A: LangGraph plan]
    P --> H{Human approval?}
    H -->|Reject| X[Stop]
    H -->|Approve| R[Stage 4B: SEC and XBRL research]
    R --> D[Stage 4C: Draft]
    D --> C[Independent Critic]
    C -->|Unsupported| V[Bounded revision]
    V --> C
    C -->|Reviewable| U[Human report-review gate]
    U -->|Approved separately| F[Authorized submission workflow]
'''

"""Phase 6D-2: independent exact-source XBRL arithmetic audit of a reviewed draft.

Uses the existing read-only, sidecar-verified offline EDGAR service. Checks that
source IDs, annual period boundaries, USD units, and displayed rounded values
match independently retrieved SEC facts. Mixed growth concepts remain a HARD
PUBLICATION BLOCKER, even when arithmetic is reproducible.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

from .stage4b_research import ResearchError

KNOWN = ('operating_margin', 'revenue_growth_yoy')
VERIFIED_COMPANIES = frozenset({'AAPL', 'ADBE', 'BBY', 'CRM', 'DG', 'GOOGL', 'HD', 'LOW', 'META', 'MSFT', 'TGT', 'ULTA'})
CLASSES = {'VERIFIED_SAME_PERIOD', 'VERIFIED_SAME_TAG', 'TAG_RECONCILIATION_REQUIRED'}
TAG_BLOCK = 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'
ROW = re.compile(r'^\|\s*([A-Z]{2,6})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([+-]?\d+(?:\.\d+)?)%\s*\|\s*([+-]?\d+(?:\.\d+)?)%\s*\|\s*([A-Z_]+)\s*\|\s*$')
HEADING = re.compile(r'^([A-Z]{2,6})\s+[—-]\s+(operating_margin|revenue_growth_yoy)\s+\(([A-Z_]+)\):\s*$')
FACT_LINE = re.compile(r'^-\s*`(CIK\d{10}\|\d{10}-\d{2}-\d{6}\|us-gaap:[A-Za-z0-9]+\|\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}\|[A-Za-z0-9]+)`\s*$')
REVENUE = {'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
           'SalesRevenueNet', 'RevenueFromContractWithCustomerIncludingAssessedTax',
           'SalesRevenueGoodsNet'}


def refuse(code: str) -> None:
    raise ResearchError('PHASE6D2_FINANCIAL_INTEGRITY: ' + code)


def _percent(value: Any) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        refuse('NONNUMERIC_PERCENT')
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError):
        refuse('NONNUMERIC_PERCENT')
    if not result.is_finite() or abs(result) > 1000000:
        refuse('NONFINITE_OR_EXCESSIVE_PERCENT')
    return result


def parse_draft_financials(markdown: str, companies: tuple[str, ...]) -> dict:
    """Parse only the canonical deterministic Writer table and operand blocks."""
    if not isinstance(markdown, str) or not markdown or len(markdown) > 180000:
        refuse('INVALID_DRAFT')
    if (not isinstance(companies, tuple) or not companies
            or any(not isinstance(c, str) or c not in VERIFIED_COMPANIES for c in companies)
            or len(set(companies)) != len(companies)):
        refuse('UNSUPPORTED_COMPANY_SCOPE')
    lines = markdown.splitlines()
    rows = {}
    for line in lines:
        match = ROW.fullmatch(line.strip())
        if match:
            tick, year, margin, growth, growth_label = match.groups()
            if tick in rows or tick not in companies or growth_label not in CLASSES:
                refuse('DUPLICATE_OR_UNEXPECTED_ROW')
            try:
                date.fromisoformat(year)
            except ValueError:
                refuse('INVALID_FISCAL_YEAR')
            rows[tick] = {'report_date': year, 'operating_margin': _percent(margin),
                          'revenue_growth_yoy': _percent(growth), 'growth_label': growth_label}
    if set(rows) != set(companies):
        refuse('MISSING_OR_EXTRA_FINANCIAL_ROWS')
    blocks: dict[tuple[str, str], dict] = {}
    for index, line in enumerate(lines):
        match = HEADING.fullmatch(line.strip())
        if not match:
            continue
        ticker, metric, label = match.groups()
        if ticker not in companies or (ticker, metric) in blocks or label not in CLASSES:
            refuse('DUPLICATE_OR_UNEXPECTED_OPERANDS')
        ids = []
        for follower in lines[index + 1:]:
            if not follower.strip():
                if ids:
                    break
                continue
            matched = FACT_LINE.fullmatch(follower.strip())
            if not matched:
                break
            ids.append(matched.group(1))
        if len(ids) != 2 or ids[0] == ids[1]:
            refuse('TWO_DISTINCT_OPERANDS_REQUIRED')
        blocks[ticker, metric] = {'classification': label, 'ids': ids}
    if set(blocks) != {(t, m) for t in companies for m in KNOWN}:
        refuse('MISSING_OR_EXTRA_METRIC_BLOCKS')
    return {'rows': rows, 'blocks': blocks}


def _annual(*, ticker: str, report_date: str, kind: str, cache) -> dict:
    """Use exact SHA/URL-sidecar-verified offline SEC service, never a raw ID lookup."""
    # Use the established three-filing research/cache window. Both operands for
    # YoY growth are explicitly verified below, so requesting five historical
    # filings is unnecessary and fails when the SEC cache holds only three.
    reply = cache.get_annual_fact(ticker, report_date, kind, years=3)
    if not isinstance(reply, dict) or reply.get('ok') is not True:
        refuse('CANONICAL_SEC_FACT_UNAVAILABLE')
    data = reply.get('data')
    if not isinstance(data, dict) or data.get('calculation_performed') is not False:
        refuse('CANONICAL_REPLY_UNTRUSTED')
    fact = data.get('fact')
    filing = data.get('filing')
    if not isinstance(fact, dict) or not isinstance(filing, dict):
        refuse('CANONICAL_REPLY_MALFORMED')
    if fact.get('ticker') != ticker or fact.get('period_end') != report_date:
        refuse('CANONICAL_TICKER_OR_DATE_MISMATCH')
    if fact.get('unit') != 'USD' or not isinstance(fact.get('fact_id'), str) or not fact['fact_id'].endswith('|USD'):
        refuse('XBRL_UNIT_NOT_USD')
    if fact.get('accession') != filing.get('accession') or filing.get('report_date') != report_date or filing.get('form') != '10-K':
        refuse('CANONICAL_ACCESSION_OR_FORM_MISMATCH')
    try:
        start = date.fromisoformat(fact['period_start'])
        end = date.fromisoformat(fact['period_end'])
        amount = Decimal(str(fact['value']))
    except (ValueError, KeyError, TypeError, InvalidOperation):
        refuse('CANONICAL_FACT_MALFORMED')
    if not 350 <= (end - start).days + 1 <= 380 or not amount.is_finite() or abs(amount) > Decimal('1e30'):
        refuse('CANONICAL_ANNUAL_DURATION_OR_AMOUNT')
    cik = filing.get('cik')
    if (not isinstance(cik, int) or isinstance(cik, bool) or
            not isinstance(fact.get('cik'), int) or fact.get('cik') != cik):
        refuse('CANONICAL_CIK_MISMATCH')
    expected_id = f"CIK{cik:010d}|{fact['accession']}|us-gaap:{fact.get('concept')}|{start}:{end}|USD"
    if fact['fact_id'] != expected_id:
        refuse('CANONICAL_FACT_ID_INCONSISTENT')
    if kind == 'revenue' and fact['concept'] not in REVENUE:
        refuse('CANONICAL_REVENUE_TAG_INVALID')
    if kind == 'operating_income' and fact['concept'] != 'OperatingIncomeLoss':
        refuse('CANONICAL_OPERATING_TAG_INVALID')
    return {'id': fact['fact_id'], 'amount': amount, 'start': start, 'end': end,
            'concept': fact['concept'], 'accession': fact['accession'], 'cik': cik}


def verify_financial_draft(bundle: dict, companies: tuple[str, ...], *, edgar=None) -> dict:
    """Read-only audit. Return a bounded receipt; never approve, sign, or publish.

    Fail closed if facts are missing or display values disagree. If different
    revenue concepts were used in successive years, arithmetic may pass but
    report must preserve a hard publication blocker.
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get('blockers'), list) or not isinstance(bundle.get('source_ids'), list):
        refuse('INVALID_BOUND_REPORT')
    text = bundle.get('markdown')
    parsed = parse_draft_financials(text, companies)
    if edgar is None:
        from .edgar_service import EdgarFactsService
        edgar = EdgarFactsService(offline=True)
    if getattr(edgar, 'offline', None) is not True:
        refuse('ONLINE_OR_UNVERIFIED_FACT_PROVIDER')
    inventory = set(bundle['source_ids'])
    rows, blocks = parsed['rows'], parsed['blocks']
    expected_inventory = set()
    checks = []
    mixed = []
    for ticker in companies:
        year = rows[ticker]['report_date']
        revenue = _annual(ticker=ticker, report_date=year, kind='revenue', cache=edgar)
        operating = _annual(ticker=ticker, report_date=year, kind='operating_income', cache=edgar)
        growth_block = blocks[ticker, 'revenue_growth_yoy']
        prior_id = growth_block['ids'][1]
        previous_date = prior_id.split('|')[3].split(':')[-1]  # only as a proposed lookup key
        try:
            current_end, prior_end = date.fromisoformat(year), date.fromisoformat(previous_date)
        except ValueError:
            refuse('INVALID_PRIOR_PERIOD')
        if current_end.year != prior_end.year + 1 or not 360 <= (current_end-prior_end).days <= 373:
            refuse('NONADJACENT_FISCAL_YEARS')
        prior = _annual(ticker=ticker, report_date=previous_date, kind='revenue', cache=edgar)
        if prior['start'] <= revenue['end'] and revenue['start'] <= prior['end']:
            refuse('OVERLAPPING_FISCAL_YEARS')
        if revenue['start'] <= prior['end'] or revenue['end'] != current_end:
            refuse('INVALID_GROWTH_PERIODS')
        if operating['start'] != revenue['start'] or operating['end'] != revenue['end'] or operating['accession'] != revenue['accession']:
            refuse('MARGIN_OPERANDS_NOT_SAME_PERIOD_AND_FILING')
        if operating['cik'] != revenue['cik'] or prior['cik'] != revenue['cik']:
            refuse('CROSS_COMPANY_XBRL_FACTS')
        if revenue['amount'] <= 0 or prior['amount'] <= 0:
            refuse('REVENUE_NONPOSITIVE')
        margin_label = blocks[ticker, 'operating_margin']['classification']
        if margin_label != 'VERIFIED_SAME_PERIOD':
            refuse('MARGIN_CLASSIFICATION_MISMATCH')
        growth_label = 'VERIFIED_SAME_TAG' if revenue['concept'] == prior['concept'] else 'TAG_RECONCILIATION_REQUIRED'
        if growth_block['classification'] != growth_label or rows[ticker]['growth_label'] != growth_label:
            refuse('GROWTH_CONCEPT_CLASSIFICATION_MISMATCH')
        values = (('operating_margin', (operating, revenue),
                   100 * operating['amount'] / revenue['amount']),
                  ('revenue_growth_yoy', (revenue, prior),
                   100 * (revenue['amount']-prior['amount']) / prior['amount']))
        for metric, operands, computed in values:
            block = blocks[ticker, metric]
            ids = [v['id'] for v in operands]
            if block['ids'] != ids or not set(ids).issubset(inventory):
                refuse('XBRL_OPERAND_ID_MISMATCH')
            expected_inventory.update(ids)
            expected = computed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if rows[ticker][metric] != expected:
                refuse('REPORTED_PERCENT_DISAGREES_WITH_SEC_FACTS')
            checks.append({'ticker': ticker, 'metric': metric,
                           'result': 'VERIFIED', 'value_percent': str(expected),
                           'classification': growth_label if metric == 'revenue_growth_yoy' else margin_label})
        if growth_label == 'TAG_RECONCILIATION_REQUIRED':
            mixed.append(ticker)
    if {s for s in inventory if isinstance(s, str) and s.startswith('CIK')} != expected_inventory:
        refuse('EXTRA_OR_MISSING_XBRL_FACT_IDS')
    if mixed and TAG_BLOCK not in bundle['blockers']:
        refuse('MIXED_REVENUE_CONCEPT_BLOCKER_MISSING')
    # Guard against a forged global reconciliation state when no discrepancy exists.
    if not mixed and TAG_BLOCK in bundle['blockers']:
        refuse('STALE_RECONCILIATION_BLOCKER')
    return {'status': 'PASS_WITH_BLOCKERS' if mixed or bundle['blockers'] else 'PASS',
            'phase': 'PHASE6D2_FINANCIAL_INTEGRITY', 'arithmetical_reconciliation_passed': True,
            'source_provenance': 'OFFLINE_SEC_EDGAR_SHA256_URL_SIDECARS',
            'verified_metrics': len(checks), 'metric_checks': checks,
            'mixed_revenue_tags': mixed, 'hard_blockers': list(bundle['blockers']),
            'publication_ready': False if bundle['blockers'] or mixed else False,
            'publication_ready_assessed': False, 'portal_registration_performed': False,
            'human_report_approved': False, 'publication_performed': False}

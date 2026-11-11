"""Phase 6D-2: read-only SEC truth checks and pre-MCP CLI integration."""
import asyncio
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from analyst_desk.phase6d2_financial_integrity import (
    parse_draft_financials, verify_financial_draft, TAG_BLOCK,
)
from analyst_desk.stage4b_research import ResearchError


FISCALS = {
    'MSFT': ('2026-06-30', '2025-06-30', 789019, '0001193125-26-323660', '0001193125-25-323660'),
    'GOOGL': ('2025-12-31', '2024-12-31', 1652044, '0001652044-26-000007', '0001652044-25-000007'),
}


def fact(ticker, fiscal, kind, amount, tag, *, last=False):
    cur, prior, cik, now_accn, prev_accn = FISCALS[ticker]
    start = (str(int(fiscal[:4]) - 1) + '-07-01') if ticker == 'MSFT' else fiscal[:4] + '-01-01'
    accession = prev_accn if last else now_accn
    id_ = f'CIK{cik:010d}|{accession}|us-gaap:{tag}|{start}:{fiscal}|USD'
    return {'ticker': ticker, 'cik': cik, 'company': ticker,
            'accession': accession, 'unit': 'USD', 'value': str(amount),
            'concept': tag, 'period_start': start, 'period_end': fiscal,
            'fact_id': id_}, {'cik': cik, 'accession': accession,
                             'report_date': fiscal, 'form': '10-K'}


def canonical():
    factmap = {}
    for ticker, (year, prior, *_rest) in FISCALS.items():
        cur_rev, prev_rev, current_op = (250, 200, 100) if ticker == 'MSFT' else (200, 160, 60)
        current_tag = 'Revenues'
        previous_tag = 'Revenues' if ticker == 'MSFT' else 'RevenueFromContractWithCustomerExcludingAssessedTax'
        factmap[ticker, year, 'revenue'] = fact(ticker, year, 'revenue', cur_rev, current_tag)
        factmap[ticker, year, 'operating_income'] = fact(ticker, year, 'operating_income', current_op, 'OperatingIncomeLoss')
        factmap[ticker, prior, 'revenue'] = fact(ticker, prior, 'revenue', prev_rev, previous_tag, last=True)
    return factmap


class VerifiedFakeEdgar:
    offline = True

    def __init__(self):
        self.data = canonical()
        self.calls = []

    def get_annual_fact(self, ticker, report_date, metric, years=3):
        self.calls.append((ticker, report_date, metric, years))
        try:
            f, filing = self.data[ticker, report_date, metric]
        except KeyError:
            return {'ok': False, 'error_code': 'NOT_FOUND'}
        return {'ok': True, 'data': {'fact': deepcopy(f), 'filing': deepcopy(filing),
                                     'calculation_performed': False}}


def bundle_for(facts=None):
    facts = facts or canonical()
    md = ['**STATUS: UNREVIEWED DRAFT — NOT APPROVED FOR PUBLICATION**',
          '| Company | Fiscal year ended | Operating margin | Revenue growth YoY | Growth-tag status |',
          '|---|---|---:|---:|---|']
    sources = []
    for tick in FISCALS:
        date = FISCALS[tick][0]
        m = '40.00' if tick == 'MSFT' else '30.00'
        gr = 'VERIFIED_SAME_TAG' if tick == 'MSFT' else 'TAG_RECONCILIATION_REQUIRED'
        md.append(f'| {tick} | {date} | {m}% | 25.00% | {gr} |')
    md.append('**XBRL fact operand IDs** (current and comparison periods; exact SEC source identifiers):')
    for ticker in FISCALS:
        current, prior = FISCALS[ticker][:2]
        margin = [facts[ticker,current,'operating_income'][0]['fact_id'],
                  facts[ticker,current,'revenue'][0]['fact_id']]
        growth = [facts[ticker,current,'revenue'][0]['fact_id'],
                  facts[ticker,prior,'revenue'][0]['fact_id']]
        for metric, ids, label in (('operating_margin',margin,'VERIFIED_SAME_PERIOD'),
                                   ('revenue_growth_yoy',growth,
                                    'VERIFIED_SAME_TAG' if ticker == 'MSFT' else 'TAG_RECONCILIATION_REQUIRED')):
            md.append(f'\n{ticker} — {metric} ({label}):')
            for id_ in ids:
                sources.append(id_)
                md.append(f'- `{id_}`')
    return {'markdown': '\n'.join(md), 'source_ids': list(dict.fromkeys(sources)),
            'blockers': [TAG_BLOCK], 'sha256': 'a'*64}


def test_clean_four_metrics_and_mixed_tag_blocker():
    edgar = VerifiedFakeEdgar()
    receipt = verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)
    assert receipt['status'] == 'PASS_WITH_BLOCKERS'
    assert receipt['verified_metrics'] == 4
    assert receipt['mixed_revenue_tags'] == ['GOOGL']
    assert receipt['publication_performed'] is False
    assert receipt['publication_ready_assessed'] is False
    assert len(edgar.calls) == 6


def test_reconciles_with_only_three_cached_annual_filings():
    """Regression for real GOOGL cache: 3 filings exist, 5 do not.

    Strictly preserve exact-source and arithmetic validation; do not fall back
    to a missing fact or change the revenue-concept publication blocker.
    """
    class ThreeYearCache(VerifiedFakeEdgar):
        def get_annual_fact(self, ticker, report_date, metric, years=3):
            if years != 3:
                self.calls.append((ticker, report_date, metric, years))
                return {'ok': False, 'error_code': 'SEC_DATA_ERROR'}
            return super().get_annual_fact(ticker, report_date, metric, years=years)

    cache = ThreeYearCache()
    receipt = verify_financial_draft(bundle_for(), ('MSFT', 'GOOGL'), edgar=cache)
    assert receipt['status'] == 'PASS_WITH_BLOCKERS'
    assert receipt['verified_metrics'] == 4
    assert receipt['mixed_revenue_tags'] == ['GOOGL']
    assert TAG_BLOCK in receipt['hard_blockers']
    assert len(cache.calls) == 6
    assert all(years == 3 for *_, years in cache.calls)
    assert not receipt['publication_performed']

    # Limiting the filing window must not reduce fact integrity enforcement.
    cache.data['GOOGL', '2025-12-31', 'revenue'][0]['unit'] = 'USDm'
    with pytest.raises(ResearchError, match='XBRL_UNIT_NOT_USD'):
        verify_financial_draft(bundle_for(), ('MSFT', 'GOOGL'), edgar=cache)


def test_schema_parser_exact_metric_contract():
    record = parse_draft_financials(bundle_for()['markdown'], ('MSFT','GOOGL'))
    assert len(record['rows']) == 2 and len(record['blocks']) == 4


@pytest.mark.parametrize('needle,replacement', [
    ('40.00%', '4000.00%'), ('25.00%', '25.01%'), ('30.00%', '03.00%'),
    ('VERIFIED_SAME_TAG |', 'TAG_RECONCILIATION_REQUIRED |'),
    ('| MSFT | 2026-06-30', '| MSFT | 2026-05-30'),
])
def test_report_values_or_classification_modified_refused(needle, replacement):
    b = bundle_for()
    b['markdown'] = b['markdown'].replace(needle, replacement, 1)
    with pytest.raises(ResearchError, match='PHASE6D2'):
        verify_financial_draft(b, ('MSFT','GOOGL'), edgar=VerifiedFakeEdgar())


def test_canonical_operand_changed_rejected():
    edgar=VerifiedFakeEdgar()
    k=('MSFT','2026-06-30','operating_income')
    edgar.data[k][0]['value']='200'
    with pytest.raises(ResearchError, match='DISAGREES_WITH_SEC_FACTS'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)


@pytest.mark.parametrize('mutator', [
    lambda b: b['source_ids'].pop(),
    lambda b: b['source_ids'].append('CIK9999999999|0001193125-26-323660|us-gaap:Revenues|2025-07-01:2026-06-30|USD'),
    lambda b: b.update(blockers=[]),
    lambda b: b.update(source_ids=[]),
])
def test_missing_extra_sources_and_missing_blocker_fail_closed(mutator):
    b=bundle_for()
    mutator(b)
    with pytest.raises(ResearchError, match='PHASE6D2'):
        verify_financial_draft(b, ('MSFT','GOOGL'), edgar=VerifiedFakeEdgar())


def test_missing_canonical_or_unverified_provider_fail_closed():
    edgar=VerifiedFakeEdgar()
    edgar.data.pop(('MSFT','2026-06-30','revenue'))
    with pytest.raises(ResearchError, match='UNAVAILABLE'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)
    edgar=VerifiedFakeEdgar()
    edgar.offline=False
    with pytest.raises(ResearchError, match='UNVERIFIED_FACT_PROVIDER'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)


def test_wrong_unit_and_bad_fact_id_rejected():
    edgar=VerifiedFakeEdgar()
    f=edgar.data['MSFT','2026-06-30','revenue'][0]
    f['unit']='USDm'
    with pytest.raises(ResearchError, match='XBRL_UNIT_NOT_USD'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)
    edgar=VerifiedFakeEdgar()
    f=edgar.data['MSFT','2026-06-30','revenue'][0]
    f['fact_id']=f['fact_id'].replace('Revenues','RevenueFromContractWithCustomerExcludingAssessedTax')
    with pytest.raises(ResearchError, match='FACT_ID_INCONSISTENT'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)


def test_wrong_period_and_cik_rejected():
    edgar=VerifiedFakeEdgar()
    edgar.data['MSFT','2025-06-30','revenue'][0]['period_start']='2025-05-01'
    with pytest.raises(ResearchError, match='DURATION'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)
    edgar=VerifiedFakeEdgar()
    edgar.data['MSFT','2026-06-30','revenue'][0]['cik']=7
    with pytest.raises(ResearchError, match='CANONICAL_CIK_MISMATCH'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)


def test_fake_provenance_flag_rejected():
    edgar=VerifiedFakeEdgar()
    original=edgar.get_annual_fact
    def modified(*args, **kwargs):
        value=original(*args,**kwargs)
        value['data']['calculation_performed']=True
        return value
    edgar.get_annual_fact=modified
    with pytest.raises(ResearchError, match='UNTRUSTED'):
        verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=edgar)


@pytest.mark.asyncio
async def test_portal_register_cli_preflight_before_any_mcp_write(monkeypatch, tmp_path):
    from analyst_desk import stage4c4_cli
    b=bundle_for()
    monkeypatch.setattr(stage4c4_cli, 'approved_plan_from_stage4a', lambda *a: {'companies':['MSFT','GOOGL']})
    monkeypatch.setattr(stage4c4_cli, 'load_reviewed_bundle', lambda *a, **kw: b)
    from analyst_desk import edgar_service
    monkeypatch.setattr(edgar_service, 'EdgarFactsService', lambda *a, **k: VerifiedFakeEdgar())
    touched=[]
    class Gateway:
        def __init__(self, root):
            touched.append('initialized')
        async def __aenter__(self):
            touched.append('entered')
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(stage4c4_cli, 'PortalMCPGateway', Gateway)
    # A corrupted source result stops the real registration CLI before MCP init.
    b['markdown'] = b['markdown'].replace('40.00%', '45.00%')
    with pytest.raises(ResearchError, match='DISAGREES_WITH_SEC_FACTS'):
        await stage4c4_cli.execute(tmp_path, SimpleNamespace(command='register',thread_id='a'*32,
                                                               manifest='evidence/dummy.json'))
    assert touched == []


def test_no_untrusted_output_written_to_results():
    receipt=verify_financial_draft(bundle_for(), ('MSFT','GOOGL'), edgar=VerifiedFakeEdgar())
    assert 'markdown' not in receipt and 'source_ids' not in receipt
    assert receipt['human_report_approved'] is False


def test_cli_out_path_must_be_inside_evidence():
    from analyst_desk import phase6d2_cli
    with pytest.raises(SystemExit):
        phase6d2_cli.main(['audit','--thread-id','a'*32,'--manifest','evidence/report.json',
                           '--out','../secrets.json'])


def test_cli_no_portal_write_and_sanitized_failure(monkeypatch, tmp_path, capsys):
    from analyst_desk import phase6d2_cli
    (tmp_path/'evidence').mkdir()
    monkeypatch.setattr(phase6d2_cli, 'approved_plan_from_stage4a', lambda *a: {'companies':['MSFT','GOOGL']})
    monkeypatch.setattr(phase6d2_cli, 'load_reviewed_bundle', lambda *a, **kw: bundle_for())
    monkeypatch.setattr(phase6d2_cli, 'EdgarFactsService', lambda *a, **k: VerifiedFakeEdgar())
    argv=['audit','--thread-id','a'*32,'--manifest','evidence/test.json',
          '--out','evidence/97_phase6d2_test.json','--project-root',str(tmp_path)]
    assert phase6d2_cli.main(argv) == 0
    recorded=(tmp_path/'evidence'/'97_phase6d2_test.json').read_text()
    assert 'PASS_WITH_BLOCKERS' in recorded and 'publication_performed' in recorded
    assert 'text' not in recorded
    # No portal, approval, signing, or publication code is imported or called.
    receipt = __import__('json').loads(recorded)
    assert receipt['publication_performed'] is False
    assert receipt['portal_registration_performed'] is False


def test_actual_stage4c_writer_format_is_parseable():
    from test_stage4c1_writer import packet_fixture, write
    plan, packet = packet_fixture(offline=True)
    markdown = write(plan, packet)['draft_markdown']
    parsed = parse_draft_financials(markdown, tuple(plan['companies']))
    assert len(parsed['blocks']) == 4
    assert parsed['rows']['GOOGL']['growth_label'] == 'TAG_RECONCILIATION_REQUIRED'
    assert parsed['rows']['MSFT']['operating_margin'] == Decimal('46.78')

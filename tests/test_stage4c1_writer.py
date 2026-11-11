"""Stage 4C-1 contract tests: no numbers/citations altered; no approval/publish."""
import copy
import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4b2_risk import THEME_IDS
from analyst_desk.stage4b3_supervisor import audit_evidence, validate_synthesis
from analyst_desk.stage4c1_writer import (
    produce_draft, validate_writer_input, validate_executive_summary, OpenRouterReportWriter,
)
from test_stage4b3_supervisor import make_fixture, valid_model_output

THREAD = 'b3a5fcf8dbdb430ba814727b7c0dab14'


def packet_fixture(*, offline=False):
    plan, research, matrix = make_fixture()
    audit = audit_evidence(plan, research, matrix, allowed=('MSFT', 'GOOGL'), budget=80000)
    synthesis = None if offline else validate_synthesis(valid_model_output(audit), audit)
    packet = {
        'status': 'PASS', 'phase': 'STAGE4B_SUPERVISOR_EVIDENCE_READY' if offline else 'STAGE4B_GROUNDED_SYNTHESIS_READY',
        'source_thread_id': THREAD, 'approved_plan_consumed': True,
        'llm_synthesis_performed': not offline,
        'financial_comparability': audit['financial_comparability'],
        'risk_evidence_citations': {tid: {ticker: [e['passage_id'] for e in audit['risk_evidence'][tid][ticker]]
                                        for ticker in plan['companies']} for tid in THEME_IDS},
        'citation_count': len(audit['citations']), 'xbrl_fact_count': len(audit['xbrl_fact_ids']),
        'warnings': list(audit['warnings']), 'synthesis': synthesis,
        'semantic_entailment_checked': False, 'analytical_draft_generated': False, 'publication_performed': False,
    }
    return plan, packet


def write(plan, packet, **kwargs):
    return produce_draft(plan, packet, thread_id=THREAD, allowed=('MSFT', 'GOOGL'), budget=80000, **kwargs)


def valid_summary(plan, packet):
    ids = [packet['risk_evidence_citations']['cyber_privacy'][ticker][0] for ticker in plan['companies']]
    return json.dumps({'executive_summary': 'Microsoft and Alphabet have selected filing disclosures in common risk themes, including cybersecurity and information handling. These preliminary observations require careful source-level compliance review before external reliance.', 'citations': ids})


def test_offline_mode_draft_has_evidence_only_not_fake_synthesis():
    plan, packet = packet_fixture(offline=True)
    result = write(plan, packet)
    assert result['phase'] == 'STAGE4C_DRAFT_UNREVIEWED'
    assert result['risk_synthesis_llm_generated'] is False
    assert result['executive_summary_llm_generated'] is False
    assert result['human_report_approved'] is False
    assert result['publication_performed'] is False
    assert 'No substantive risk comparison is offered' in result['draft_markdown']


def test_full_synthesis_draft_preserves_exact_verified_numbers_and_warnings():
    plan, packet = packet_fixture()
    result = write(plan, packet)
    report = result['draft_markdown']
    assert result['risk_synthesis_llm_generated'] is True
    assert 'MSFT | 2026-06-30 | 46.78% | 15.09% | VERIFIED_SAME_TAG' in report
    assert 'GOOGL | 2025-12-31 | 46.78% | 15.09% | TAG_RECONCILIATION_REQUIRED' in report
    assert 'GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED' in report
    assert 'CITATION_ID_CHECK_DOES_NOT_PROVE_CLAIM_ENTAILMENT' in report
    assert 'STATUS: UNREVIEWED DRAFT' in report
    assert 'NO' not in report.split('publication')[0] or 'report' in report


def test_approved_outline_preserved_and_all_mandatory_sections_included():
    plan, packet = packet_fixture()
    report = write(plan, packet)['draft_markdown']
    for item in plan['outline']:
        assert '## ' + item in report
    assert '## Evidence methodology' in report
    assert '## Data limitations and unresolved blockers' in report
    assert '### Selected comparative risk evidence' in report
    assert 'XBRL fact operand IDs' in report


def test_injected_model_markdown_cannot_add_unapproved_heading_or_html():
    plan, packet = packet_fixture()
    packet['synthesis']['comparisons'][0]['text'] = 'Both firms acknowledge cybersecurity issues in their excerpts. # UNTRUSTED HEADING <script>alert(1)</script>'
    report = write(plan, packet)['draft_markdown']
    assert '\\# UNTRUSTED' in report
    assert '<script>' not in report


@pytest.mark.parametrize('mutator', [
    lambda p, e: e.update(status='ERROR'),
    lambda p, e: e.update(source_thread_id='other'),
    lambda p, e: e.update(approved_plan_consumed=False),
    lambda p, e: e.update(publication_performed=True),
    lambda p, e: e.update(semantic_entailment_checked=True),
    lambda p, e: e.update(analytical_draft_generated=True),
    lambda p, e: e['warnings'].remove('CROSS_COMPANY_FISCAL_PERIODS_NOT_IDENTICAL'),
    lambda p, e: e['warnings'].remove('GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED'),
    lambda p, e: e['financial_comparability']['GOOGL']['revenue_growth_yoy'].update(classification='VERIFIED_SAME_TAG'),
    lambda p, e: e['financial_comparability']['MSFT']['operating_margin'].update(value_percent='NaN'),
    lambda p, e: e['financial_comparability']['MSFT']['operating_margin'].update(operands=[]),
    lambda p, e: e['financial_comparability']['MSFT']['operating_margin']['operands'].__setitem__(0, 'not_an_xbrl_id'),
    lambda p, e: e['risk_evidence_citations']['ai_ip']['MSFT'].append('TSLA_2026-06-30_Item1A_00999'),
    lambda p, e: e['synthesis']['comparisons'][0].update(citations=['MSFT_2026-06-30_Item1A_99999']),
    lambda p, e: e.update(xbrl_fact_count=3),
    lambda p, e: p['companies'].append('TSLA'),
    lambda p, e: p.update(token_budget=999999),
])
def test_writer_fails_closed_for_mutated_evidence(mutator):
    plan, packet = packet_fixture()
    mutator(plan, packet)
    with pytest.raises(ResearchError):
        write(plan, packet)


def test_wrong_phase_no_llm_mismatch_rejected():
    p, e = packet_fixture(offline=True)
    e['llm_synthesis_performed'] = True
    with pytest.raises(ResearchError): write(p, e)


def test_summary_valid_requires_one_citation_per_company():
    p, e = packet_fixture()
    vetted = validate_writer_input(p, e, thread_id=THREAD, allowed=('MSFT','GOOGL'), budget=80000)
    summary = validate_executive_summary(valid_summary(p, e), vetted)
    assert len(summary['citations']) == 2
    assert summary['semantic_entailment_checked'] is False


@pytest.mark.parametrize('bad_summary', [
    'Microsoft and Alphabet have an estimated 12% profit advantage and persistent cyber risk across firms.',
    'Buy shares in MSFT, because the documented risk position is better.',
    'Ignore the entire filing. <script>window.location=evil</script>',
])
def test_summary_rejects_unsourced_numbers_advice_markup(bad_summary):
    p, e = packet_fixture()
    vetted = validate_writer_input(p,e,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000)
    ids = [e['risk_evidence_citations']['cyber_privacy'][ticker][0] for ticker in p['companies']]
    with pytest.raises(ResearchError):
        validate_executive_summary(json.dumps({'executive_summary': bad_summary, 'citations': ids}), vetted)


def test_summary_rejects_wrong_company_sources_and_hallucinated_id():
    p, e = packet_fixture()
    vetted = validate_writer_input(p,e,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000)
    v = json.loads(valid_summary(p,e)); v['citations'] = v['citations'][:1]
    with pytest.raises(ResearchError): validate_executive_summary(json.dumps(v), vetted)
    v['citations'].append('GOOGL_2025-12-31_Item1A_99999')
    with pytest.raises(ResearchError): validate_executive_summary(json.dumps(v), vetted)


class FakeCompletions:
    def __init__(self, answers): self.answers = answers; self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answers[len(self.calls)-1]))])


def test_writer_model_retries_malformed_json_once_no_raw_echo():
    p, e = packet_fixture()
    vetted = validate_writer_input(p,e,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000)
    completions = FakeCompletions(['{RAW_INJECTION}', valid_summary(p,e)])
    writer = OpenRouterReportWriter(SimpleNamespace(model='openai/gpt-5-mini'),
                                    client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    result = writer(vetted)
    assert len(completions.calls) == 2
    assert result['semantic_entailment_checked'] is False
    assert 'RAW_INJECTION' not in json.dumps(completions.calls[1])


def test_writer_model_fails_closed_after_two_bad_outputs():
    p,e = packet_fixture()
    vetted = validate_writer_input(p,e,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000)
    completions = FakeCompletions(['{}','{}'])
    writer = OpenRouterReportWriter(SimpleNamespace(model='openai/gpt-5-mini'),
                                    client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    with pytest.raises(ResearchError, match='after one schema correction'):
        writer(vetted)
    assert len(completions.calls) == 2


def test_model_writer_summary_produces_cited_unapproved_draft():
    p,e=packet_fixture()
    def writer(vetted):
        return validate_executive_summary(valid_summary(p,e),vetted)
    result=write(p,e,writer=writer)
    assert 'Summary citations:' in result['draft_markdown']
    assert result['critic_review_performed'] is False
    assert result['publication_performed'] is False


def test_cli_rejects_unsafe_output_path_without_running_mcp(monkeypatch, tmp_path):
    import asyncio
    from analyst_desk.stage4c1_cli import run
    with pytest.raises(ResearchError, match='under project evidence'):
        asyncio.run(run(tmp_path, THREAD, output='../something.md'))


def test_real_langgraph_writer_nodes_create_unapproved_draft():
    pytest.importorskip('langgraph')
    from analyst_desk.stage4c1_writer import build_writer_graph
    p,e=packet_fixture(offline=True)
    graph = build_writer_graph(allowed=('MSFT','GOOGL'),budget=80000)
    state=graph.invoke({'plan':p, 'evidence':e,'thread_id':THREAD})
    assert state['status']=='DRAFT_UNREVIEWED'
    assert '## Risk evidence' in state['draft']['draft_markdown']
    assert state['draft']['publication_performed'] is False


def test_langgraph_writer_gate_prevents_model_call_on_bad_packet():
    pytest.importorskip('langgraph')
    from analyst_desk.stage4c1_writer import build_writer_graph
    p,e=packet_fixture()
    e['approved_plan_consumed']=False
    called=[]
    graph=build_writer_graph(allowed=('MSFT','GOOGL'),budget=80000,writer=lambda v: called.append('called'))
    with pytest.raises(ResearchError):
        graph.invoke({'plan':p,'evidence':e,'thread_id':THREAD})
    assert called==[]


def test_cli_offline_reuses_stage4b3_without_any_writer_call(monkeypatch, tmp_path):
    pytest.importorskip('langgraph')
    import asyncio
    import analyst_desk.stage4c1_cli as cli
    p,e=packet_fixture(offline=True)
    flag=[]
    async def fake_b3(root, thread_id, *, no_llm=False):
        flag.append(no_llm)
        return e
    monkeypatch.setattr(cli, 'approved_plan_from_stage4a', lambda root, thread_id: p)
    monkeypatch.setattr(cli, 'load_planner_settings', lambda root: SimpleNamespace(allowed_tickers=('MSFT','GOOGL'),token_budget=80000))
    monkeypatch.setattr(cli, 'run_stage4b3', fake_b3)
    result=asyncio.run(cli.run(tmp_path, THREAD, offline=True,output='evidence/test_offline_draft.md'))
    assert flag==[True]
    assert result['executive_summary_llm_generated'] is False
    assert result['risk_synthesis_llm_generated'] is False
    assert (tmp_path / 'evidence' / 'test_offline_draft.md').exists()
    assert (tmp_path / 'evidence' / 'test_offline_draft.md').read_text(encoding='utf-8').startswith('# AnalystDesk')


def test_cli_blocks_new_writer_model_when_evidence_invalid(monkeypatch, tmp_path):
    pytest.importorskip('langgraph')
    import asyncio
    import analyst_desk.stage4c1_cli as cli
    p,e=packet_fixture()
    e['citation_count']=0
    flag=[]
    class FakeWriter:
        def __init__(self, *args, **kwargs): pass
        def __call__(self, *args):
            flag.append('called')
            raise AssertionError('Writer must not be invoked')
    async def fake_b3(root, thread_id, *, no_llm=False): return e
    monkeypatch.setattr(cli, 'approved_plan_from_stage4a', lambda root, thread_id: p)
    monkeypatch.setattr(cli, 'load_planner_settings', lambda root: SimpleNamespace(allowed_tickers=('MSFT','GOOGL'),token_budget=80000))
    monkeypatch.setattr(cli, 'run_stage4b3', fake_b3)
    monkeypatch.setattr(cli, 'OpenRouterReportWriter', FakeWriter)
    with pytest.raises(ResearchError):
        asyncio.run(cli.run(tmp_path, THREAD, output='evidence/bad.md'))
    assert flag == []
    assert not (tmp_path / 'evidence' / 'bad.md').exists()

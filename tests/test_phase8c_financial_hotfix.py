"""Phase 8C1 live financial-outline hotfix regression tests."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from analyst_desk.phase7d_evaluation import (
    _load_fixed_fixture, SyntheticCanonicalMCP, ScriptedWriterClient,
    scripted_critic, scripted_rewriter,
)
from analyst_desk.stage4c1_writer import (
    OpenRouterReportWriter, produce_draft,
)
from analyst_desk.phase8c_architecture import (
    ArchitectureEvalError, financial_digest, paired_downstream_evaluation,
)

ROOT=Path(__file__).resolve().parents[1]
THREAD='b3a5fcf8dbdb430ba814727b7c0dab14'


def _render(outline):
    plan, evidence=_load_fixed_fixture(ROOT)
    plan['outline']=outline
    return produce_draft(plan, evidence, thread_id=THREAD,
                         allowed=('MSFT','GOOGL'), budget=80000)['draft_markdown']


def test_approved_custom_heading_not_named_financial_findings():
    md=_render(['Reporting scope','Performance by issuer','Risk factors','Methodology','Limitations'])
    assert '## Performance by issuer' in md
    assert '## Financial findings' not in md
    assert len(financial_digest(md))==64


def test_original_heading_still_supported():
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    assert len(financial_digest(md))==64


def test_heading_change_only_preserves_hash():
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    assert financial_digest(md)==financial_digest(md.replace('## Financial findings','## Financial metrics',1))


def test_any_metric_mutation_changes_hash():
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    assert financial_digest(md)!=financial_digest(md.replace('46.78%', '46.79%',1))


def test_any_xbrl_operand_change_changes_hash():
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    assert financial_digest(md)!=financial_digest(md.replace('us-gaap:OperatingIncomeLoss', 'us-gaap:OperatingIncomeLosx',1))


def test_crlf_accepted_without_changing_hash():
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    assert financial_digest(md)==financial_digest(md.replace('\n','\r\n'))


def test_duplicate_section_rejected():
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    sec='## Additional metrics\n\n'+md.split('## Financial findings\n\n',1)[1].split('\n## ',1)[0]
    with pytest.raises(ArchitectureEvalError,match='AMBIGUOUS'):
        financial_digest(md+'\n'+sec)


@pytest.mark.parametrize('mutate',[
    lambda md: md.replace('| Company | Fiscal year ended', '| Issuer | Fiscal year ended'),
    lambda md: md.replace('**XBRL fact operand IDs**', '**Removed operands**'),
    lambda md: md.replace('All percentages above come from','These percentages appeared from'),
    lambda md: md.replace('TAG_RECONCILIATION_REQUIRED','TAG_RECONCILIATION_IGNORED'),
])
def test_financial_subsection_tampering_fails_closed(mutate):
    md=_render(['Scope and sources','Financial findings','Risk evidence'])
    with pytest.raises(ArchitectureEvalError):financial_digest(mutate(md))


def test_full_three_arm_pipeline_with_nonstandard_financial_heading():
    plan,evidence=_load_fixed_fixture(ROOT)
    plan['outline']=['Report scope','Comparative performance','Risk and evidence','Data limits']
    writer=lambda _:OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
        client=ScriptedWriterClient('neutral'),editorial_lessons=[])
    result=asyncio.run(paired_downstream_evaluation(
        plan,evidence,thread_id=THREAD,allowed=('MSFT','GOOGL'),budget=80000,
        call=SyntheticCanonicalMCP(),writer_factory=writer,
        critic_factory=lambda _:scripted_critic,
        rewriter_factory=lambda _:scripted_rewriter,max_revisions=2))
    assert result['status']=='PASS_PAIRED_PILOT'
    assert len({r['financial_section_sha256'] for r in result['results']})==1
    assert all('REVENUE_GROWTH_TAG_RECONCILIATION_OPEN' in r['hard_blockers']
               for r in result['results'])
    assert result['portal_publication_performed'] is False

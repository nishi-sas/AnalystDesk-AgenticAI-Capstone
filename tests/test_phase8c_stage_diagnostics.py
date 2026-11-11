"""Phase8C diagnostic safety tests; no external calls or real SEC requests."""
from __future__ import annotations
import asyncio
from pathlib import Path
from types import SimpleNamespace
import pytest
from analyst_desk.phase7d_evaluation import (
    _load_fixed_fixture, SyntheticCanonicalMCP, ScriptedWriterClient,
    scripted_critic, scripted_rewriter,
)
from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4c1_writer import OpenRouterReportWriter
from analyst_desk.phase8c_architecture import (
    ArchitectureEvalError, _failure_code, _stage_error, paired_downstream_evaluation,
)

ROOT=Path(__file__).resolve().parents[1]
THREAD='b3a5fcf8dbdb430ba814727b7c0dab14'
SECRET='sk-REDACT-MUST-NOT-PRINT-dont-expose'


def _run(writer=None, critic=None, rewriter=None):
    plan,evidence=_load_fixed_fixture(ROOT)
    real_writer=lambda _:OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
        client=ScriptedWriterClient('neutral'),editorial_lessons=[])
    return asyncio.run(paired_downstream_evaluation(plan,evidence,thread_id=THREAD,
        allowed=('MSFT','GOOGL'),budget=80000,call=SyntheticCanonicalMCP(),
        writer_factory=writer or real_writer,
        critic_factory=critic or (lambda _:scripted_critic),
        rewriter_factory=rewriter or (lambda _:scripted_rewriter)))


def test_successful_comparison_same_receipt():
    result=_run()
    assert result['status']=='PASS_PAIRED_PILOT'
    assert [r['configuration'] for r in result['results']]==['C0','C1','C2']


def test_c0_critic_failure_identified_without_sensitive_content():
    def critic_factory(mode):
        def fail(*a):raise ResearchError('Critic returned bad output: '+SECRET)
        return fail
    with pytest.raises(ArchitectureEvalError,match='STAGE=C0_CRITIC;CODE=CRITIC_SOURCE_OR_OUTPUT_REJECTED') as err:
        _run(critic=critic_factory)
    assert SECRET not in str(err.value)


def test_c1_writer_failure_identified_without_secret():
    def writer_factory(mode):
        if mode=='C1':
            def bad_writer(*a):raise ResearchError('Writer refused: '+SECRET)
            return bad_writer
        return OpenRouterReportWriter(SimpleNamespace(model='phase7d-scripted-model'),
           client=ScriptedWriterClient('neutral'),editorial_lessons=[])
    with pytest.raises(ArchitectureEvalError,match='STAGE=C1_DRAFT;CODE=WRITER_INPUT_OR_OUTPUT_REJECTED') as err:
        _run(writer=writer_factory)
    assert SECRET not in str(err.value)


def test_c2_revision_failure_identified(monkeypatch):
    async def fail(*args,**kwargs):
        raise ResearchError('Revision failed with '+SECRET)
    monkeypatch.setattr('analyst_desk.phase8c_architecture.run_revision_loop',fail)
    with pytest.raises(ArchitectureEvalError,match='STAGE=C2_WRITER_CRITIC_REVISION;CODE=REVISION_CONTRACT_FAILED') as err:
        _run()
    assert SECRET not in str(err.value)


@pytest.mark.parametrize('name,expected',[
    ('AuthenticationError','MODEL_AUTHENTICATION_ERROR'),
    ('RateLimitError','MODEL_RATE_LIMIT'),
    ('APITimeoutError','MODEL_TIMEOUT'),
    ('APIConnectionError','MODEL_CONNECTION_ERROR'),
    ('BadRequestError','MODEL_BAD_REQUEST'),
    ('SomeUnknownProviderError','UNCLASSIFIED_OPERATION_ERROR')])
def test_provider_error_classification_has_no_payload(name,expected):
    fake=type(name,(Exception,),{})(SECRET)
    assert _failure_code(fake)==expected
    assert SECRET not in str(_stage_error('C0_CRITIC',fake))


@pytest.mark.parametrize('message,expected',[
 ('LLM synthesis invalid after one correction: '+SECRET,'SYNTHESIS_SCHEMA_REJECTED'),
 ('Writer summary invalid after one schema correction: '+SECRET,'WRITER_SCHEMA_REJECTED'),
 ('Critic JSON invalid after bounded repair: '+SECRET,'CRITIC_SCHEMA_REJECTED'),
 ('Research error '+SECRET,'RESEARCH_CONTRACT_FAILED')])
def test_research_error_whitelist_only(message,expected):
    exc=ResearchError(message)
    assert _failure_code(exc)==expected
    assert SECRET not in str(_stage_error('B3_SHARED_UPSTREAM',exc))


def test_unknown_stage_whitelisted_not_user_reflected():
    err=_stage_error('USER_SUPPLIED_'+SECRET,ValueError(SECRET))
    assert str(err)=='STAGE=UNKNOWN_STAGE;CODE=UNCLASSIFIED_OPERATION_ERROR'


def test_financial_check_still_fails_closed():
    # No relaxation to report/table validation introduced by diagnostic wrapper.
    from analyst_desk.phase8c_architecture import financial_digest
    with pytest.raises(ArchitectureEvalError,match='FINANCIAL_SECTION_MISSING'):
        financial_digest('report without metric table')

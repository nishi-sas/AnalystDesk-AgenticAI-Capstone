"""Regression: malformed model explanations remain fail-closed without crashing 4C3."""
import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4b_research import ResearchError
from analyst_desk.stage4c2_critic import (
    CRITIC_REASON_SCHEMA_BLOCKER,
    CRITIC_REASON_SCHEMA_MESSAGE,
    OpenRouterComplianceCritic,
    validate_verdict,
)
from analyst_desk.stage4c3_revision import run_revision_loop
from test_stage4c2_critic import FakeMCP, _ModelClient
from test_stage4c3_revision import THREAD, ALLOW, BUDGET, packet_fixture, summary_writer

PID = 'MSFT_2026-06-30_Item1A_00011'


def _invalid_reason(reason, claim_id='cyber_privacy', citations=None):
    return json.dumps({
        'claim_id': claim_id, 'verdict': 'SUPPORTED',
        'reason': reason, 'citations': citations if citations is not None else [PID],
    })


def _source(truncated=False):
    return {'passages': {PID: {'text': 'Official SEC disclosure text.', 'truncated': truncated}}}


def test_two_bad_reasons_become_uncertain_not_false_support():
    client = _ModelClient([_invalid_reason('No'), _invalid_reason('https://bad.example')])
    critic = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client)
    verdict = critic('cyber_privacy', 'MSFT describes a risk', [PID], _source())
    assert verdict == {'claim_id': 'cyber_privacy', 'verdict': 'UNCERTAIN',
                       'reason': CRITIC_REASON_SCHEMA_MESSAGE, 'citations': [], 'human_verified': False}
    assert len(client.calls) == 2
    assert 'https://bad.example' not in client.calls[1]['messages'][-1]['content']
    assert 'https://bad.example' not in str(client.calls)
    assert validate_verdict(json.dumps({k: verdict[k] for k in ('claim_id', 'verdict', 'reason', 'citations')}),
                            expected_id='cyber_privacy', allowed_citations=[PID])['verdict'] == 'UNCERTAIN'


def test_bad_reason_then_valid_reason_preserves_strict_two_call_budget():
    client = _ModelClient([_invalid_reason('x'), _invalid_reason('Risk is described in the supplied canonical source.')])
    critic = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client)
    v = critic('cyber_privacy', 'MSFT describes a risk', [PID], _source())
    assert v['verdict'] == 'SUPPORTED'
    assert len(client.calls) == 2


def test_invalid_citation_or_truncated_evidence_never_falls_back_as_supported():
    bad = _invalid_reason('The cited evidence supports the described disclosure.', citations=['FORGED'])
    client = _ModelClient([bad, bad])
    critic = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client)
    with pytest.raises(ResearchError, match='after bounded repair'):
        critic('cyber_privacy', 'Some risk', [PID], _source())
    client2 = _ModelClient([_invalid_reason('x'), _invalid_reason('x')])
    critic2 = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client2)
    with pytest.raises(ResearchError, match='after bounded repair'):
        critic2('cyber_privacy', 'Some risk', [PID], _source(truncated=True))


@pytest.mark.asyncio
async def test_revision_graph_stops_without_rewrite_when_reason_repair_exhausted():
    plan, evidence = packet_fixture()
    revised = []

    class ModelClient:
        def __init__(self):
            self.counts = {}
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, *, model, messages):
            payload = json.loads(messages[1]['content'])
            claim = payload['claim_id']
            self.counts[claim] = self.counts.get(claim, 0) + 1
            reply = json.dumps({
                'claim_id': claim,
                'verdict': 'SUPPORTED',
                'reason': 'x' if claim == 'ai_ip' else 'The reported risk appears in the cited sources.',
                'citations': payload['allowed_citations'],
            })
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

    client = ModelClient()
    model = OpenRouterComplianceCritic(SimpleNamespace(model='openai/gpt-5-mini'), client=client)

    def rewriter(**kwargs):
        revised.append(kwargs)
        raise AssertionError('Malformed critic feedback must not initiate editorial revisions')

    result = await run_revision_loop(plan, evidence, thread_id=THREAD, allowed=ALLOW,
                                     budget=BUDGET, call=FakeMCP(), writer=summary_writer,
                                     critic=model, rewriter=rewriter)
    assert result['status'] == 'PASS'
    assert result['phase'] == 'STAGE4C_REVIEW_BLOCKED'
    assert result['revision_count'] == 0
    assert result['hard_blockers'] and CRITIC_REASON_SCHEMA_BLOCKER in result['hard_blockers']
    assert 'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN' in result['hard_blockers']
    assert revised == []
    assert client.counts['ai_ip'] == 2
    assert result['human_report_approved'] is False and result['publication_performed'] is False

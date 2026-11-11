"""Regression checks for Stage 4C-3 model instructions and existing fail-closed behavior."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from analyst_desk.stage4c3_revision import OpenRouterTargetedRewriter, RewriterOutputRetriesExhausted

IDS = ['TGT_2026-01-31_Item1A_00026', 'HD_2026-02-01_Item1A_00028']


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.messages_seen = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model, messages):
        self.messages_seen.append(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.response))])


def _args():
    return dict(
        claim_id='cyber_privacy',
        previous_text='Target and Home Depot face cybersecurity risks. Conclusions remain provisional until human review.',
        allowed_citations=IDS,
        feedback='Attribute response controls only to Target; do not claim Home Depot disclosed identical controls.',
        source_packet={'passages': {
            IDS[0]: {'text': 'Target describes cybersecurity incident response programs.', 'truncated': False},
            IDS[1]: {'text': 'Home Depot describes third-party cybersecurity vulnerabilities.', 'truncated': False},
        }},
        plan={'companies': ['TGT', 'HD']},
    )


def test_rewriter_prompt_keeps_review_status_outside_claims():
    proposal = {'text': 'Target describes incident response programs; Home Depot identifies third-party vulnerabilities.', 'citations': IDS}
    fake = FakeModel(json.dumps(proposal))
    result = OpenRouterTargetedRewriter(SimpleNamespace(model='test/model'), client=fake)(**_args())
    assert result == proposal
    system = fake.messages_seen[0][0]['content']
    assert 'Report-review status belongs in document metadata' in system
    assert 'Attribute company-specific assertions explicitly' in system
    assert 'Preserve that conclusions need independent human review' not in system


def test_rewriter_does_not_relax_citation_scope():
    fake = FakeModel(json.dumps({'text': 'Revised content', 'citations': ['OTHER_UNAUTHORIZED_ID']}))
    with pytest.raises(RewriterOutputRetriesExhausted):
        OpenRouterTargetedRewriter(SimpleNamespace(model='test/model'), client=fake)(**_args())
    assert len(fake.messages_seen) == 2


def test_rewriter_prompt_instructs_summary_to_omit_unsubstantiated_themes():
    proposal = {'text': 'Target and Home Depot discuss distinct cybersecurity and technology risks.', 'citations': IDS}
    fake = FakeModel(json.dumps(proposal))
    OpenRouterTargetedRewriter(SimpleNamespace(model='test/model'), client=fake)(**_args())
    system = fake.messages_seen[0][0]['content']
    assert 'Include only risk themes supported by the allowed citations' in system
    assert 'omit unsupported comparisons, unrequested peers and procedural disclaimers' in system

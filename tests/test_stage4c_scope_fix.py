"""Regression checks for the prompt-scope separation fix (no network or LLM calls)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from analyst_desk.stage4a_config import PROJECT_ROOT
from analyst_desk.stage4c1_writer import OpenRouterReportWriter


class PromptCaptured(Exception):
    pass


class CaptureCompletions:
    def __init__(self):
        self.messages = None

    def create(self, **kwargs):
        self.messages = kwargs['messages']
        raise PromptCaptured


def test_writer_uses_approved_company_scope_not_old_peers():
    capture = CaptureCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=capture))
    writer = OpenRouterReportWriter(SimpleNamespace(model='test/offline'), client=client)
    validated = {
        'plan': {'companies': ['TGT', 'HD']},
        'comparisons': [],
        'warnings': [],
    }
    with pytest.raises(PromptCaptured):
        writer(validated)
    system = capture.messages[0]['content']
    payload = capture.messages[1]['content']
    assert 'Mention both Microsoft and Alphabet' not in system
    assert 'approved companies' in system
    assert 'unrequested companies' in system
    assert 'review-status disclaimers' in system
    assert '"TGT"' in payload and '"HD"' in payload


def test_supervisor_does_not_embed_workflow_status_as_cited_fact():
    content = (PROJECT_ROOT / 'src/analyst_desk/stage4b3_supervisor.py').read_text(encoding='utf-8')
    assert 'say retrieval was insufficient' not in content
    assert 'All conclusions remain provisional until human/compliance review.' not in content
    assert 'workflow warnings' in content
    assert 'review-status sentences' in content


def test_existing_critic_and_revision_gates_remain_in_place():
    content = (PROJECT_ROOT / 'src/analyst_desk/stage4c3_revision.py').read_text(encoding='utf-8')
    assert 'RewriterOutputRetriesExhausted' in content
    assert 'CANONICAL_SOURCE_CONTEXT_TRUNCATED' in content
    assert 'STAGE4C_READY_FOR_HUMAN_REVIEW' in content

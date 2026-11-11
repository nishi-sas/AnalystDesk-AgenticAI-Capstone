"""Targeted offline tests; never call OpenRouter."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRITER_SOURCE = ROOT / 'src' / 'analyst_desk' / 'stage4c1_writer.py'


def test_writer_prompt_and_retry_target_without_changing_hard_validator():
    src = WRITER_SOURCE.read_text(encoding='utf-8')
    assert 'AD_STAGE4C_WRITER_LENGTH_DIAGNOSTIC_20261103' in src
    assert '180-320 characters IN THE executive_summary STRING VALUE' in src
    assert 'The executive_summary STRING VALUE must have 180-320 characters' in src
    assert "not 90 <= len(summary.strip()) <= 550" in src
    assert "Writer summary must cite both companies" in src
    assert "Writer executive summary invented a citation" in src
    ast.parse(src)


def test_installer_is_idempotent_and_read_only_when_applied():
    import importlib.util
    installer_path = ROOT / 'tools' / 'apply_stage4c_writer_length_fix.py'
    spec = importlib.util.spec_from_file_location('_writer_length_patch', installer_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = WRITER_SOURCE.read_text(encoding='utf-8')
    assert mod.patch(src) == src


def test_writer_two_invalid_short_summaries_fail_closed_with_length_only(monkeypatch):
    import analyst_desk.stage4c1_writer as mod
    from analyst_desk.stage4b_research import ResearchError

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            self.calls.append(kwargs)
            raw = json.dumps({'executive_summary': 'Short text', 'citations': ['ADBE_example', 'LOW_example']})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])

    def validator(raw, validated):
        val = json.loads(raw)['executive_summary']
        if not 90 <= len(val.strip()) <= 550:
            raise ResearchError('Writer executive summary must be 90-550 characters')
        raise AssertionError('Unexpected valid sample')

    monkeypatch.setattr(mod, 'validate_executive_summary', validator)
    fake = FakeClient()
    writer = mod.OpenRouterReportWriter(SimpleNamespace(model='local-fake'), client=fake)
    sample = {'plan': {'companies': ['ADBE', 'LOW']}, 'comparisons': [], 'warnings': []}
    with pytest.raises(ResearchError, match='received 10 characters'):
        writer(sample)
    assert len(fake.calls) == 2
    assert '180-320 characters IN THE executive_summary STRING VALUE' in fake.calls[0]['messages'][0]['content']
    assert 'received 10 characters' in fake.calls[1]['messages'][-1]['content']
    assert 'Short text' not in fake.calls[1]['messages'][-1]['content']

"""Verify patch's schema-retry anchor survives previous prompt modifications."""
import ast
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('_writer_length_patch_v2', ROOT/'tools'/'apply_stage4c_writer_length_fix.py')
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_writer_retry_ast_matches_prior_prompt_variants():
    for variant in ('. Retry: exactly executive_summary and citations.', '. Retry with the updated two-company evidence rules.'):
        source = (
            'class OpenRouterReportWriter:\n'
            '    def __call__(self, validated):\n'
            '        try:\n'
            '            pass\n'
            '        except ResearchError as exc:\n'
            '            messages.append({\'role\': \'user\', \'content\': \'Previous JSON failed strict validation: \' + str(exc) +\n'
            '                             ' + repr(variant) + '})\n'
        )
        result=mod.replace_writer_retry_ast(source)
        ast.parse(result)
        assert 'The executive_summary STRING VALUE must have 180-320 characters' in result
        assert 'safe_reason' in result

def test_patch_unchanged_when_marked():
    marked = 'x=1\n# ' + mod.MARKER + '\n'
    assert mod.patch(marked) == marked

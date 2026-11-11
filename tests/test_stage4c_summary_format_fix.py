"""Tests targeted formatting correction without network or model calls."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src' / 'analyst_desk' / 'stage4c3_revision.py'


def _fn():
    source = SOURCE.read_text(encoding='utf-8')
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and
              n.name == '_normalize_rewriter_summary_whitespace')
    ns = {'ResearchError': type('ResearchError', (Exception,), {})}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<test>', 'exec'), ns)
    return ns['_normalize_rewriter_summary_whitespace'], ns['ResearchError'], source


def test_linebreak_is_whitespace_only():
    fn, _, _ = _fn()
    assert fn('Adobe faces cyber risk.\nLowe\'s discusses regulatory exposure.') == (
        "Adobe faces cyber risk. Lowe's discusses regulatory exposure.")
    assert fn('Adobe  and\n\nLowe\'s') == "Adobe and Lowe's"


def test_numbers_are_still_rejected():
    fn, err, _ = _fn()
    try:
        fn('Adobe growth 10 percent; Lowe\'s exposure.')
    except err as exc:
        assert 'prohibited numbers' in str(exc)
    else:
        raise AssertionError('Numeric prose was incorrectly accepted')


def test_semantic_and_provenance_guards_still_present():
    _, _, source = _fn()
    assert 'AD_STAGE4C_SUMMARY_FORMAT_20261102' in source
    assert 'REWRITER_SUMMARY_NUMBERS_REJECTED' in source
    assert "not set(proposal['citations']).issubset(set(ids))" in source
    assert 'validate_executive_summary(json.dumps({' in source
    assert 'out = produce_draft(' in source
    assert 'RewriterOutputRetriesExhausted' in source
    assert "'human_report_approved':False" in source
    assert "'publication_performed':False" in source

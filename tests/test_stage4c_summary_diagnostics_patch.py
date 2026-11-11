"""Non-network acceptance checks for the installed Stage 4C patch."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'src' / 'analyst_desk'


def src(name):
    p = PKG / name
    assert p.is_file(), f'Project file missing: {p}'
    source = p.read_text(encoding='utf-8')
    ast.parse(source, filename=str(p))
    return source


def test_writer_company_specific_and_grounded():
    text = src('stage4c1_writer.py')
    assert 'Attribute each company-specific risk explicitly' in text
    assert 'Do not infer causal relationships' in text
    assert 'do not insert review-status disclaimers' in text


def test_rewriter_keeps_citation_scope_and_fixed_limits():
    text = src('stage4c3_revision.py')
    assert 'REWRITER_CITATION_SCOPE_REJECTED' in text
    assert 'REVISION' not in text or 'MAX_REVISIONS = 2' in text
    assert "not set(proposal['citations']).issubset(set(ids))" in text
    assert "no digits; cite each company" in text
    assert 'RewriterOutputRetriesExhausted' in text


def test_graph_stops_on_unacceptable_rewrite():
    text = src('stage4c3_revision.py')
    assert "'phase':'STAGE4C_REVIEW_BLOCKED'" in text
    assert "'revision_failure': {'code': _safe_rewriter_failure_code(exc)" in text
    assert "'revision_failure':state.get('revision_failure')" in text
    assert "'revision_count':len(actions)" in text
    assert "'human_report_approved':False" in text
    assert "'publication_performed':False" in text


def test_safe_diagnostic_mapping_cannot_echo_model_data():
    code = src('stage4c3_revision.py')
    node = next(n for n in ast.parse(code).body
                if isinstance(n, ast.FunctionDef) and n.name == '_safe_rewriter_failure_code')
    compiled = compile(ast.Module(body=[node], type_ignores=[]), 'diagnostic', 'exec')
    namespace = {}
    exec(compiled, namespace)
    fn = namespace['_safe_rewriter_failure_code']
    assert fn(ValueError('Rewriter returned unauthorized citations')) == 'REWRITER_CITATION_SCOPE_REJECTED'
    assert fn(ValueError('Rewriter output schema invalid')) == 'REWRITER_JSON_SCHEMA_REJECTED'
    assert fn(ValueError('secret=sk-should-not-appear')) == 'REWRITER_OUTPUT_VALIDATION_FAILED'
    assert 'sk-' not in fn(ValueError('secret=sk-should-not-appear'))


def test_cli_manifest_exposes_diagnostic_without_approval():
    cli = src('stage4c3_cli.py')
    assert "'revision_failure':result.get('revision_failure')" in cli
    assert "'publication_performed':False" in cli
    assert "'human_report_approved':False" in cli

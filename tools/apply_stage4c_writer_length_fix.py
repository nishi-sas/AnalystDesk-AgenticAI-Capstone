"""Install a narrow Stage 4C Writer length-prompt and safe diagnostic fix.

Run from AnalystDesk repository root. No network or LLM calls.
This does not change the 90-550-char hard validation, citations, Critic, or HITL.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import shutil

SOURCE = Path('src/analyst_desk/stage4c1_writer.py')
MARKER = 'AD_STAGE4C_WRITER_LENGTH_DIAGNOSTIC_20261103'


def replace_one(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f'{label}: source anchor mismatch (found {text.count(old)}); no changes made')
    return text.replace(old, new, 1)



def replace_writer_retry_ast(text: str) -> str:
    """Replace just the Writer schema-repair message, independent of earlier wording."""
    import ast
    tree = ast.parse(text)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OpenRouterReportWriter']
    if len(classes) != 1:
        raise ValueError('Writer class not uniquely identified; no changes made')
    methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == '__call__']
    if len(methods) != 1:
        raise ValueError('Writer call method not uniquely identified; no changes made')
    candidates = []
    for n in ast.walk(methods[0]):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute):
            call = n.value
            if (call.func.attr == 'append' and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == 'messages'
                    and 'Previous JSON failed strict validation:' in ast.get_source_segment(text, n)):
                candidates.append(n)
    if len(candidates) != 1:
        raise ValueError(f'Writer schema retry AST anchor mismatch (found {len(candidates)}); no changes made')
    node = candidates[0]
    lines = text.splitlines(keepends=True)
    # Verify the selected expression occupies full physical lines.
    beginning = lines[node.lineno - 1][:node.col_offset]
    remainder = lines[node.end_lineno - 1][node.end_col_offset:].strip()
    if beginning.strip() or remainder:
        raise ValueError('Writer retry spans partial statements; no changes made')
    indent = ' ' * node.col_offset
    replacement = (
        indent + "messages.append({'role': 'user', 'content': 'Previous JSON failed strict validation: ' + safe_reason +\n"
        + indent + "                 '. Retry with exactly executive_summary and citations. The executive_summary STRING VALUE must have 180-320 characters, ' +\n"
        + indent + "                 'not words or JSON length; use two concise company-specific sentences, one per company. ' +\n"
        + indent + "                 'No digits or Markdown; cite canonical passage IDs for both companies, no unsupported causal claims.'})\n"
    )
    lines[node.lineno - 1:node.end_lineno] = [replacement]
    result = ''.join(lines)
    ast.parse(result)
    return result

def patch(text: str) -> str:
    if MARKER in text:
        return text
    text = replace_one(text,
        "'Only return a JSON object with exactly keys executive_summary (90-550 characters) and citations (array of canonical passage IDs). '",
        "'Only return a JSON object with exactly keys executive_summary (90-550 characters) and citations (array of canonical passage IDs). '"
        "\n            'Aim for 180-320 characters IN THE executive_summary STRING VALUE, not the JSON response. '"
        "\n            'Write two concise, complete sentences: one attributed to each company using the filing comparisons. '"
        "\n            'Count characters, not words or tokens. Do not add filler merely to reach length. '",
        'initial Writer length instruction')
    old = """            except ResearchError as exc:
                if attempt:
                    raise ResearchError('Writer summary invalid after one schema correction: ' + str(exc)) from None
                # No model's raw response, SEC excerpt or credentials are echoed back.
                messages.append({'role': 'user', 'content': 'Previous JSON failed strict validation: ' + str(exc) +"""
    new = """            except ResearchError as exc:
                # Diagnose only the length of a JSON string, never log model text.
                safe_reason = str(exc)
                if safe_reason == 'Writer executive summary must be 90-550 characters':
                    try:
                        parsed = json.loads(response.choices[0].message.content)
                        summary_value = parsed.get('executive_summary') if isinstance(parsed, dict) else None
                        if isinstance(summary_value, str):
                            safe_reason += f' (received {len(summary_value.strip())} characters)'
                    except (ValueError, TypeError):
                        pass
                if attempt:
                    raise ResearchError('Writer summary invalid after one schema correction: ' + safe_reason) from None
                # No model's raw response, SEC excerpt or credentials are echoed back.
                messages.append({'role': 'user', 'content': 'Previous JSON failed strict validation: ' + safe_reason +"""
    text = replace_one(text, old, new, 'Writer length-only diagnostic')
    # The retry wording has changed in previous AnalystDesk patches. Instead of
    # requiring an exact phrase, find the unique Writer exception's messages.append
    # call by its AST location, and replace only that statement.
    text = replace_writer_retry_ast(text)
    text = replace_one(text, 'class OpenRouterReportWriter:', f'# {MARKER}\nclass OpenRouterReportWriter:', 'Writer patch marker')
    ast.parse(text, filename=str(SOURCE))
    return text


def install(root: Path) -> str:
    root = root.resolve()
    path = root / SOURCE
    if not path.is_file():
        raise ValueError('Not in AnalystDesk root; stage4c1_writer.py not found')
    original = path.read_text(encoding='utf-8')
    result = patch(original)
    if result == original:
        return 'ALREADY_APPLIED: no files changed'
    backup = root / 'backups' / ('stage4c_writer_length_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')) / SOURCE
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    try:
        path.write_text(result, encoding='utf-8')
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except Exception:
        shutil.copy2(backup, path)
        raise
    return (f'PATCHED: {SOURCE}\nBACKUP: {backup}\n'
            'Writer target: 180-320 characters; hard validator remains 90-550. '
            'Length-only diagnostics; no citations, Critic, HITL or financial logic changed.')


if __name__ == '__main__':
    try:
        print(install(Path.cwd()))
    except (ValueError, OSError, SyntaxError) as exc:
        raise SystemExit('INSTALLATION ABORTED: ' + str(exc))

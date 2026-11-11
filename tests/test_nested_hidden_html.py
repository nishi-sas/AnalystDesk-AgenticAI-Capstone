"""Regression cases for a stale BeautifulSoup descendant after ancestor.decompose()."""
from analyst_desk.document_parsing import html_blocks


def _visible_text(raw: bytes) -> str:
    return '\n'.join(block.text for block in html_blocks(raw))


def test_hidden_parent_with_styled_child_is_not_traversed():
    raw = (b'<html><body>'
           b'<div style="display:none"><p style="visibility:hidden">LEAKED_SECRET</p></div>'
           b'<p>VISIBLE_SEC_REPORT_TEXT</p>'
           b'</body></html>')
    text = _visible_text(raw)
    assert 'VISIBLE_SEC_REPORT_TEXT' in text
    assert 'LEAKED_SECRET' not in text


def test_nested_hidden_descendants_and_visible_styled_sibling():
    raw = (b'<html><body>'
           b'<div style="visibility:hidden">'
           b'<p style="display:none">HIDDEN_NESTED_TEXT</p>'
           b'</div>'
           b'<p style="font-weight:bold">VISIBLE_BOLD_TEXT</p>'
           b'<p style="display:none">HIDDEN_SIBLING_TEXT</p>'
           b'</body></html>')
    text = _visible_text(raw)
    assert 'VISIBLE_BOLD_TEXT' in text
    assert 'HIDDEN_NESTED_TEXT' not in text
    assert 'HIDDEN_SIBLING_TEXT' not in text

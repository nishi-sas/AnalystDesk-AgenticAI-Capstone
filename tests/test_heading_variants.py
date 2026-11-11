"""Regression cases for fragmented headings in SEC iXBRL HTML."""
import hashlib

from analyst_desk.document_parsing import heading_item, html_blocks, find_sections, passages_from_html


def _meta(raw):
    return {"ticker": "TEST", "accession": "0000000000-26-000001",
            "report_date": "2026-06-30", "filing_date": "2026-09-01",
            "url": "https://www.sec.gov/Archives/edgar/data/123/example.htm",
            "sha256": hashlib.sha256(raw).hexdigest()}


def _long(txt):
    return " ".join([txt] * 24)


def test_split_words_are_still_known_headings():
    assert heading_item("ITEM 1A. RIS K FACTORS") == "1A"
    assert heading_item("ITEM 8. FIN ANCIAL STATEMENTS AND SUPPLEMENTARY DATA") == "8"
    assert heading_item("ITEM 7. MANAGE MENT'S DISCUSSION") == "7"
    assert heading_item("ITEM 8") is None
    assert heading_item("Item 1A risks are discussed elsewhere") is None
    assert heading_item("Item 8 of the report is mentioned for reference") is None


def test_standalone_code_followed_by_title_is_section_start():
    raw = ("<html><body>"
           "<table><tr><td>ITEM 1A</td><td>Risk Factors</td><td>7</td></tr></table>"
           "<p>ITEM 1A</p><p>RIS K FACTORS</p><p>" + _long("Risk of changes in demand.") + "</p>"
           "<p>ITEM 1B. UNRESOLVED STAFF COMMENTS</p><p>No issues.</p>"
           "<p>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS</p>"
           "<p>" + _long("Financial performance and liquidity.") + "</p>"
           "<p>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES</p>"
           "<p>Risk discussion.</p>"
           "<p>ITEM 8</p><p>FIN ANCIAL</p><p>STATEMENTS AND SUPPLEMENTARY DATA</p>"
           "<p>" + _long("Balance sheet and auditor report.") + "</p>"
           "<p>ITEM 9. CHANGES IN AND DISAGREEMENTS</p>"
           "</body></html>").encode()
    blocks = html_blocks(raw)
    found = find_sections(blocks)
    assert found["1A"][0] < found["7"][0] < found["8"][0]
    passages, stats = passages_from_html(raw, _meta(raw))
    assert set(p["item"] for p in passages) == {"1A", "7", "8"}
    assert stats["sections"]["1A"]["characters"] < 2000


def test_prose_with_item_number_not_taken_as_heading():
    # The parser requires a recognised title, not merely a mention of Item numbers.
    assert heading_item("ITEM 1A. Our business faces increased risks") is None
    assert heading_item("Item 8: see financial discussion in another note") is None

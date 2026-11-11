"""Stage 2B synthetic 10-K extraction tests; no external requests or LLM."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from analyst_desk.document_parsing import (
    DocumentParseError, find_sections, heading_item, html_blocks,
    passages_from_html, process_manifest,
)
from analyst_desk.parse_cli import main


LONG_RISK = "Risk and uncertainty affecting operating performance and demand. " * 12
LONG_MD_A = "Management reviewed revenue performance, liquidity, and capital allocation. " * 12
LONG_STATEMENTS = "Financial statements and accompanying notes contain material disclosures. " * 12


def fixture_html(toc=True, include_item8=True):
    index = """
      <table><tr><td>ITEM 1A.</td><td>Risk Factors</td><td>12</td></tr>
             <tr><td>ITEM 7.</td><td>Management Discussion and Analysis</td><td>65</td></tr></table>
    """ if toc else ""
    return (f"""<!DOCTYPE html><html><body><h1>Annual Report</h1>{index}
     <p>ITEM 1A.RISK FACTORS</p><p>{LONG_RISK}</p>
     <p>Item 7 of this filing is referenced in this section, but this is not a heading.</p>
     <h3>ITEM 1B. UNRESOLVED STAFF COMMENTS</h3><p>None.</p>
     <h3>ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</h3>
     <div><p>{LONG_MD_A}</p></div>
     <table><tr><th>Year</th><th>Revenue</th></tr><tr><td>2025</td><td>100 | USD</td></tr></table>
     <p>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK</p><p>Market risks.</p>
     {('<h3>ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA</h3><p>'+LONG_STATEMENTS+'</p>') if include_item8 else ''}
     <table><tr><th>Balance sheet</th><th>USD</th></tr><tr><td>Cash</td><td>100</td></tr></table>
     <p>ITEM 9. CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS</p><p>None.</p>
    </body></html>""").encode("utf-8")


def meta(raw):
    return {"ticker": "TEST", "accession": "0000000000-25-000001",
            "report_date": "2025-12-31", "filing_date": "2026-02-01",
            "url": "https://www.sec.gov/Archives/edgar/data/9999/000000000025000001/report.htm",
            "sha256": hashlib.sha256(raw).hexdigest()}


def test_heading_classifier_does_not_treat_prose_as_heading():
    assert heading_item("ITEM 1A.RISK FACTORS") == "1A"
    assert heading_item("ITEM 7.MANAGEMENT’S DISCUSSION AND ANALYSIS") == "7"
    assert heading_item("ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES") == "7A"
    assert heading_item("Item 1A risks are referenced but this sentence is explanatory") is None
    assert heading_item("ITEM 7") is None


def test_table_of_contents_does_not_override_full_sections():
    blocks = html_blocks(fixture_html())
    found = find_sections(blocks)
    assert found["1A"][0] < found["7"][0] < found["8"][0]
    passages, stats = passages_from_html(fixture_html(), meta(fixture_html()))
    risk_text = " ".join(p["text"] for p in passages if p["item"] == "1A")
    assert "Risk and uncertainty" in risk_text
    assert "Management reviewed revenue" not in risk_text
    assert stats["sections"]["7"]["tables"] == 1


def test_table_rows_preserved_as_table_passages():
    raw = fixture_html()
    passages, _ = passages_from_html(raw, meta(raw))
    tables = [p for p in passages if p["is_table"]]
    assert any("| 2025 | 100 \\| USD |" in p["text"] for p in tables)
    assert all(p["kind"] == "table" for p in tables)
    assert any(p["item"] == "8" and "Balance sheet" in p["text"] for p in tables)
    assert all("source_sha256" in p for p in passages)


def test_stable_passage_ids_and_provenance():
    raw = fixture_html()
    a, _ = passages_from_html(raw, meta(raw))
    b, _ = passages_from_html(raw, meta(raw))
    assert [p["passage_id"] for p in a] == [p["passage_id"] for p in b]
    assert all(p["accession"] == meta(raw)["accession"] for p in a)
    assert len({p["passage_id"] for p in a}) == len(a)


def test_missing_required_item_fails_loudly():
    raw = fixture_html(include_item8=False)
    with pytest.raises(DocumentParseError, match="Item 8"):
        passages_from_html(raw, meta(raw))


def test_tampered_document_is_rejected():
    raw = fixture_html()
    with pytest.raises(DocumentParseError, match="SHA256 mismatch"):
        passages_from_html(raw + b"<p>altered</p>", meta(raw))


def test_long_paragraph_is_chunked():
    raw = fixture_html().replace(b"</body>", b"<p>" + b"DETAILS " * 300 + b"</p></body>")
    passages, _ = passages_from_html(raw, meta(raw), max_chars=600)
    assert any(p["item"] == "7" for p in passages)
    assert all(len(p["text"]) <= 600 for p in passages if not p["is_table"])


def write_cache_fixture(tmp_path):
    root = tmp_path / "data" / "edgar_cache"
    path = root / "documents" / "CIK0000009999" / "000000000025000001" / "report.htm"
    path.parent.mkdir(parents=True)
    raw = fixture_html()
    path.write_bytes(raw)
    obj = {**meta(raw), "local_path": str(path)}
    sidecar = {k: v for k, v in obj.items() if k != "local_path"}
    path.with_name(path.name + ".meta.json").write_text(json.dumps(sidecar), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([obj]), encoding="utf-8")
    return root, manifest


def test_process_manifest_and_cli(tmp_path):
    cache, manifest = write_cache_fixture(tmp_path)
    chunks, summaries = process_manifest(manifest, cache_root=cache)
    assert chunks and summaries[0]["passage_count"] == len(chunks)
    outfile = tmp_path / "passages.jsonl"
    summaryfile = tmp_path / "summary.json"
    assert main(["--manifest", str(manifest), "--cache", str(cache),
                 "--output", str(outfile), "--summary", str(summaryfile)]) == 0
    assert len(outfile.read_text(encoding="utf-8").splitlines()) == len(chunks)


def test_manifest_path_traversal_rejected(tmp_path):
    cache, manifest = write_cache_fixture(tmp_path)
    items = json.loads(manifest.read_text(encoding="utf-8"))
    items[0]["local_path"] = str(tmp_path / "other" / "report.htm")
    manifest.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(DocumentParseError, match="escapes SEC cache"):
        process_manifest(manifest, cache_root=cache)

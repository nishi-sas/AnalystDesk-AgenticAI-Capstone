"""Offline regression tests for sidecar corpus selection; NO SEC requests."""
import hashlib
import json
from pathlib import Path

import pytest
from tools import build_verified_coverage as m


def example_record(ticker, year, n=1):
    accession = f"{n:018d}"
    return {"ticker": ticker, "report_date": f"{year}-12-31",
            "accession": accession,
            "local_path": f"data/edgar_cache/documents/CIK0000000001/{accession}/{ticker.lower()}-{year}.htm"}


def stub_output(ticker, manifest):
    summaries, passages = [], []
    for record in manifest:
        date = record["report_date"]
        sections = {k: {"characters": 500, "tables": 1 if k == "8" else 0} for k in m.ITEMS}
        summaries.append({"ticker": ticker, "report_date": date,
                          "sections": sections, "passage_count": 3})
        for item in m.ITEMS:
            passages.append({"ticker": ticker, "report_date": date, "item": item,
                             "passage_id": f"{ticker}_{date}_{item}", "text": "a" * 400,
                             "source_url": "https://www.sec.gov/Archives/edgar/data/1/example.htm",
                             "accession": record["accession"]})
    return passages, summaries, m.verify_parser_output(ticker, manifest, passages, summaries)


def setup_repo(tmp_path):
    root = tmp_path / "repo"
    records = []
    for ticker in (s for group in m.SECTORS.values() for s in group):
        for year in (2025, 2024, 2023):
            r = example_record(ticker, year, n=year)
            records.append(r)
            path = root / r["local_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SEC TEST DOCUMENT" * 100)
    m._write_json(root / "evidence" / "10k_html_manifest.json", records)
    (root / "data" / "parsed").mkdir(parents=True)
    (root / "data" / "parsed" / "10k_passages.jsonl").write_text("DO NOT MODIFY\n")
    return root


def test_candidate_lists_are_entirely_new():
    m.unique_queue(m.SECTORS, m.REPLACEMENTS)
    with pytest.raises(m.CoverageError):
        m.unique_queue(m.SECTORS, {**m.REPLACEMENTS, "technology": ("MSFT",)})


def test_three_distinct_reporting_periods():
    rows = [example_record("AAPL", 2024, 2024), example_record("AAPL", 2025, 2025), example_record("AAPL", 2023, 2023)]
    assert len(m.grouped_three(rows, "AAPL")) == 3
    with pytest.raises(m.CoverageError):
        m.grouped_three(rows[:2] + rows[1:2], "AAPL")


def test_bad_source_url_is_rejected():
    rows = [example_record("AAPL", y, y) for y in (2025, 2024, 2023)]
    passages, summaries, result = stub_output("AAPL", rows)
    assert result["status"] == "PARSER_VALIDATED"
    passages[0]["source_url"] = "https://evil.example/Archives/fake.htm"
    with pytest.raises(m.CoverageError, match="SEC Archives"):
        m.verify_parser_output("AAPL", rows, passages, summaries)


def test_item8_absence_is_rejected():
    rows = [example_record("AAPL", y, y) for y in (2025, 2024, 2023)]
    passages, summaries, _ = stub_output("AAPL", rows)
    summaries[0]["sections"].pop("8")
    with pytest.raises(m.CoverageError, match="missing"):
        m.verify_parser_output("AAPL", rows, passages, summaries)


def test_full_company_replacement_same_sector_and_original_untouched(tmp_path, monkeypatch):
    root = setup_repo(tmp_path)

    def fake_download(ticker, stage_root, repo_root):
        rows = [example_record(ticker, y, y) for y in (2025, 2024, 2023)]
        for row in rows:
            path = stage_root / row["local_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"REPLACEMENT SEC DOCUMENT" * 100)
            Path(str(path) + ".meta.json").write_text('{"test": "SEC metadata stub"}')
        return rows

    def fake_parse(ticker, docs, stage_root):
        if ticker == "ORCL":
            raise ValueError("Missing or empty Item 8")
        return stub_output(ticker, docs)

    monkeypatch.setattr(m, "download_replacement", fake_download)
    monkeypatch.setattr(m, "parse_and_validate", fake_parse)
    report = m.build(root)
    assert report["status"] == "PASS"
    assert report["selected_filings"] == 36
    assert "ORCL" not in report["selection"]["technology"]
    assert "ADBE" in report["selection"]["technology"]
    assert len(report["selection"]["technology"]) == 6
    assert len(report["selection"]["commerce_retail"]) == 6
    assert (root / "data/parsed/10k_passages.jsonl").read_text() == "DO NOT MODIFY\n"
    assert len(json.loads((root / "evidence/10k_html_manifest.json").read_text())) == 36
    pointer = json.loads((root / "data/verified_coverage/current.json").read_text())
    corpus = root / pointer["corpus"]
    assert len(corpus.read_text().splitlines()) == 108
    assert (root / "data/edgar_cache/documents/CIK0000000001/000000000000002025/adbe-2025.htm").exists()


def test_insufficient_replacements_cannot_publish(tmp_path, monkeypatch):
    root = setup_repo(tmp_path)

    def fake_fail(ticker, docs, stage):
        if ticker == "ORCL":
            raise ValueError("Missing Item 8")
        return stub_output(ticker, docs)

    def fake_download(ticker, stage_root, repo_root):
        raise ValueError("No 10-K documents for candidate")

    monkeypatch.setattr(m, "parse_and_validate", fake_fail)
    monkeypatch.setattr(m, "download_replacement", fake_download)
    with pytest.raises(m.CoverageError, match="queue exhausted"):
        m.build(root)
    assert not (root / "data/verified_coverage/current.json").exists()
    assert (root / "data/parsed/10k_passages.jsonl").read_text() == "DO NOT MODIFY\n"


def test_corrupt_original_document_is_rejected(tmp_path):
    root = setup_repo(tmp_path)
    rec = example_record("ORCL", 2025, 2025)
    p = root / rec["local_path"]
    p.write_text("bad")
    with pytest.raises(m.CoverageError, match="suspiciously short"):
        m.safe_document_path(rec, root)


def test_rejects_path_traversal(tmp_path):
    root = setup_repo(tmp_path)
    r = example_record("ORCL", 2025, 2025)
    r["local_path"] = "data/edgar_cache/../../secret.htm"
    with pytest.raises(m.CoverageError, match="Unsafe"):
        m.safe_document_path(r, root)

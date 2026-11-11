"""Stage 3B tests use only synthetic SEC fixture files; no real networking."""
import hashlib
import json
from pathlib import Path

import pytest

from analyst_desk.edgar_service import EdgarFactsService
from analyst_desk.edgar_mcp_server import create_server
from analyst_desk.sec_client import TICKER_URL, DATA_URL


def write_sidecar(path: Path, url: str) -> None:
    raw = path.read_bytes()
    path.with_suffix(".meta.json").write_text(json.dumps({
        "url": url, "sha256": hashlib.sha256(raw).hexdigest(), "status_code": 200,
        "fetched_utc": "2026-10-24T00:00:00Z",
    }), encoding="utf-8")


@pytest.fixture
def audited(mock_sec_cache):
    root = mock_sec_cache
    write_sidecar(root / "company_tickers.json", TICKER_URL)
    write_sidecar(root / "submissions" / "CIK0000789019.json",
                  DATA_URL + "/submissions/CIK0000789019.json")
    write_sidecar(root / "companyfacts" / "CIK0000789019.json",
                  DATA_URL + "/api/xbrl/companyfacts/CIK0000789019.json")
    return EdgarFactsService(root, offline=True)


def test_metadata_annual_filings_and_provenance(audited):
    response = audited.list_annual_filings("msft", years=3)
    assert response["ok"]
    info = response["data"]
    assert info["count"] == 3
    assert [f["report_date"] for f in info["filings"]] == [
        "2025-06-30", "2024-06-30", "2023-06-30"]
    assert all(f["filing_url"].startswith("https://www.sec.gov/Archives/")
               for f in info["filings"])
    assert len(info["source_files"]) == 2
    assert response["provenance"]["offline"] is True


def test_facts_are_unmodified_and_match_accession(audited):
    result = audited.get_annual_facts("MSFT", 3)
    assert result["ok"], result
    assert result["data"]["count"] == 3
    assert result["data"]["calculation_performed"] is False
    assert len(result["data"]["source_files"]) == 3
    vals = [(v["revenue"]["value"], v["operating_income"]["value"])
            for v in result["data"]["annual"]]
    assert vals == [("75", "18.75"), ("80", "20.0"), ("100", "25.0")]
    assert all(v["revenue"]["accession"] == v["operating_income"]["accession"]
               for v in result["data"]["annual"])
    assert all("|us-gaap:" in v["revenue"]["fact_id"]
               for v in result["data"]["annual"])


def test_exact_year_and_fact_id(audited):
    result = audited.get_annual_fact("MSFT", "2024-06-30", "revenue")
    assert result["ok"]
    fact = result["data"]["fact"]
    assert fact["value"] == "80"
    assert fact["period_end"] == "2024-06-30"
    assert fact["accession"] == "0000789019-24-000222"


@pytest.mark.parametrize("ticker,years", [
    ("../../.env", 3), ("MSFT/foo", 3), ("", 3), ("A" * 20, 3),
    ("MSFT", 0), ("MSFT", 6), ("MSFT", True), ("MSFT", "3"),
])
def test_invalid_list_calls_rejected_before_io(audited, ticker, years):
    result = audited.list_annual_filings(ticker, years)
    assert not result["ok"]
    assert result["error_code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("day,metric", [
    ("2025-02-31", "revenue"), ("June 2025", "revenue"),
    ("2025-06-30", "cash flow"), ("2025-06-30", "Assets"),
])
def test_invalid_fact_call_rejected(audited, day, metric):
    result = audited.get_annual_fact("MSFT", day, metric)
    assert not result["ok"] and result["error_code"] == "INVALID_ARGUMENT"


def test_nonexistent_fiscal_year_returns_not_found(audited):
    result = audited.get_annual_fact("MSFT", "2022-06-30", "revenue", years=3)
    assert result["error_code"] == "NOT_FOUND"


def test_tampered_companyfacts_cache_refused(audited):
    file = audited.cache_dir / "companyfacts" / "CIK0000789019.json"
    file.write_text(file.read_text() + " ", encoding="utf-8")
    result = audited.get_annual_facts("MSFT", 3)
    assert result["error_code"] == "SOURCE_INTEGRITY_ERROR"


def test_tampered_submissions_cache_refused(audited):
    file = audited.cache_dir / "submissions" / "CIK0000789019.json"
    file.write_text(file.read_text() + " ", encoding="utf-8")
    result = audited.list_annual_filings("MSFT", 1)
    assert result["error_code"] == "SOURCE_INTEGRITY_ERROR"


def test_ticker_cache_missing_sidecar_refused(audited):
    (audited.cache_dir / "company_tickers.meta.json").unlink()
    result = audited.list_annual_filings("MSFT", 1)
    assert result["error_code"] == "SOURCE_INTEGRITY_ERROR"


def test_url_changed_in_meta_refused(audited):
    path = audited.cache_dir / "company_tickers.meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["url"] = "https://example.com/unsafe"
    path.write_text(json.dumps(meta), encoding="utf-8")
    result = audited.list_annual_filings("MSFT", 1)
    assert result["error_code"] == "SOURCE_INTEGRITY_ERROR"


def test_wrong_status_in_meta_refused(audited):
    path = audited.cache_dir / "company_tickers.meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["status_code"] = 404
    path.write_text(json.dumps(meta), encoding="utf-8")
    result = audited.list_annual_filings("MSFT", 1)
    assert result["error_code"] == "SOURCE_INTEGRITY_ERROR"


def test_missing_companyfacts_fails_offline(audited):
    (audited.cache_dir / "companyfacts" / "CIK0000789019.json").unlink()
    (audited.cache_dir / "companyfacts" / "CIK0000789019.meta.json").unlink()
    result = audited.get_annual_facts("MSFT", 1)
    assert result["error_code"] == "SEC_DATA_ERROR"


def test_cache_status_no_external_fetch(audited):
    result = audited.edgar_status()
    assert result["ok"]
    assert result["data"]["cache"]["submissions_count"] == 1
    assert result["data"]["cache"]["companyfacts_count"] == 1
    assert result["data"]["offline"]


def test_no_derived_metric_in_edgar_tool_output(audited):
    result = audited.get_annual_facts("MSFT", 1)
    assert result["ok"]
    assert "operating_margin" not in json.dumps(result)
    assert "calculator" not in json.dumps(result)


def test_fastmcp_tool_discovery_and_dispatch_when_available(audited):
    pytest.importorskip("fastmcp")
    import asyncio
    from fastmcp import Client

    async def run():
        async with Client(create_server(audited)) as client:
            tools = sorted(t.name for t in await client.list_tools())
            assert tools == ["edgar_status", "get_annual_fact", "get_annual_facts", "list_annual_filings"]
            res = (await client.call_tool("get_annual_fact", {
                "ticker": "MSFT", "report_date": "2025-06-30", "metric": "operating_income"})).data
            assert res["ok"] and res["data"]["fact"]["value"] == "25.0"
            invalid = (await client.call_tool("list_annual_filings", {
                "ticker": "../../secret", "years": 1})).data
            assert invalid["error_code"] == "INVALID_ARGUMENT"
    asyncio.run(run())

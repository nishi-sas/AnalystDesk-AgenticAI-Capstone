"""Stage 3C calculation tests use only synthetic SEC fixtures, no internet."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from analyst_desk.calculation_service import CalculationService, InvalidRequest, WorkerFailure
from analyst_desk.calc_worker import calculate, CalculationError
from analyst_desk.edgar_service import EdgarFactsService
from analyst_desk.calculation_mcp_server import create_server
from analyst_desk.sec_client import TICKER_URL, DATA_URL


def sidecar(path: Path, url: str):
    path.with_suffix(".meta.json").write_text(json.dumps({
        "url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status_code": 200, "fetched_utc": "2026-10-24T00:00:00Z",
    }), encoding="utf-8")


@pytest.fixture
def calc(mock_sec_cache):
    root = mock_sec_cache
    sidecar(root / "company_tickers.json", TICKER_URL)
    sidecar(root / "submissions" / "CIK0000789019.json",
            DATA_URL + "/submissions/CIK0000789019.json")
    sidecar(root / "companyfacts" / "CIK0000789019.json",
            DATA_URL + "/api/xbrl/companyfacts/CIK0000789019.json")
    return CalculationService(root)


def test_margin_run_in_child_with_provenance(calc):
    response = calc.calculate_operating_margin("MSFT", "2025-06-30")
    assert response["ok"], response
    result = response["data"]
    assert result["value_percent"] == "25.00"
    assert result["formula"] == "100 * operating_income / revenue"
    assert len(result["operands"]) == 2
    assert all("|us-gaap:" in o for o in result["operands"])
    assert result["execution"]["separate_process"]
    assert not result["execution"]["os_hardened_sandbox"]
    assert len(result["source_urls"]) == 1


def test_yoy_growth_run_in_child_with_provenance(calc):
    response = calc.calculate_revenue_growth("MSFT", "2025-06-30", "2024-06-30")
    assert response["ok"], response
    assert response["data"]["value_percent"] == "25.00"
    assert response["data"]["formula"] == "100 * (current_revenue - prior_revenue) / prior_revenue"
    assert len(response["data"]["source_urls"]) == 2
    assert response["data"]["operands"][0] != response["data"]["operands"][1]


@pytest.mark.parametrize("ticker,day", [
    ("../../.env", "2025-06-30"), ("MSFT/foo", "2025-06-30"),
    ("", "2025-06-30"), ("MSFT", "2025-02-31"),
    ("MSFT", "June 2025"), ("MSFT", 2025), (None, "2025-06-30"),
])
def test_invalid_calls_fail_before_sec_io(calc, ticker, day):
    assert calc.calculate_operating_margin(ticker, day)["error_code"] == "INVALID_ARGUMENT"


def test_nonadjacent_fiscal_periods_refused(calc):
    response = calc.calculate_revenue_growth("MSFT", "2025-06-30", "2023-06-30")
    assert not response["ok"]
    assert response["error_code"] == "INVALID_ARGUMENT"


def test_reversed_periods_refused(calc):
    response = calc.calculate_revenue_growth("MSFT", "2024-06-30", "2025-06-30")
    assert response["error_code"] == "INVALID_ARGUMENT"


def test_same_year_refused(calc):
    response = calc.calculate_revenue_growth("MSFT", "2025-06-30", "2025-06-30")
    assert response["error_code"] == "INVALID_ARGUMENT"


def test_source_cache_tamper_refused(calc):
    facts = calc.edgar.cache_dir / "companyfacts" / "CIK0000789019.json"
    facts.write_text(facts.read_text(encoding="utf-8") + " ", encoding="utf-8")
    response = calc.calculate_operating_margin("MSFT", "2025-06-30")
    assert response["error_code"] == "WORKER_FAILURE"
    assert "SOURCE_INTEGRITY_ERROR" in response["error_message"]


def test_no_sec_data_return_synthetic_values(calc):
    response = calc.calculate_operating_margin("GOOGL", "2025-12-31")
    assert not response["ok"]
    assert response["error_code"] == "WORKER_FAILURE"


def test_calc_status_advertises_limits(calc):
    result = calc.calc_status()
    assert result["ok"]
    assert not result["data"]["arbitrary_code_allowed"]
    assert not result["data"]["os_hardened_sandbox"]
    assert result["data"]["offline_verified_source"]


def test_non_offline_edgar_forbidden(calc):
    with pytest.raises(InvalidRequest):
        CalculationService(edgar=EdgarFactsService(calc.edgar.cache_dir, offline=False))


def test_worker_rejects_mismatched_accessions(calc):
    op = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "operating_income")["data"]["fact"]
    rev = calc.edgar.get_annual_fact("MSFT", "2024-06-30", "revenue")["data"]["fact"]
    with pytest.raises(CalculationError):
        calculate({"operation": "operating_margin", "a": op, "b": rev})


def test_worker_rejects_forged_fact_id(calc):
    op = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "operating_income")["data"]["fact"]
    rev = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "revenue")["data"]["fact"]
    rev["fact_id"] = "CIK0000000000|bad"
    with pytest.raises(CalculationError):
        calculate({"operation": "operating_margin", "a": op, "b": rev})


def test_worker_rejects_bad_formula(calc):
    op = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "operating_income")["data"]["fact"]
    rev = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "revenue")["data"]["fact"]
    with pytest.raises(CalculationError):
        calculate({"operation": "exec_code", "a": op, "b": rev})


def test_worker_rejects_zero_revenue(calc):
    op = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "operating_income")["data"]["fact"]
    rev = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "revenue")["data"]["fact"]
    rev["value"] = "0"
    with pytest.raises(CalculationError):
        calculate({"operation": "operating_margin", "a": op, "b": rev})


def test_worker_rejects_nan(calc):
    op = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "operating_income")["data"]["fact"]
    rev = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "revenue")["data"]["fact"]
    rev["value"] = "NaN"
    with pytest.raises(CalculationError):
        calculate({"operation": "operating_margin", "a": op, "b": rev})


def test_worker_rejects_different_company(calc):
    op = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "operating_income")["data"]["fact"]
    rev = calc.edgar.get_annual_fact("MSFT", "2025-06-30", "revenue")["data"]["fact"]
    rev["ticker"] = "GOOGL"
    with pytest.raises(CalculationError):
        calculate({"operation": "operating_margin", "a": op, "b": rev})


def test_worker_timeout_handled(calc, tmp_path):
    script = tmp_path / "wait.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    test_service = CalculationService(edgar=calc.edgar, timeout_seconds=0.2, worker_path=script)
    result = test_service.calculate_operating_margin("MSFT", "2025-06-30")
    assert result["error_code"] == "WORKER_FAILURE"


def test_worker_malformed_output_handled(calc, tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("print('oops')\n", encoding="utf-8")
    test_service = CalculationService(edgar=calc.edgar, worker_path=script)
    result = test_service.calculate_operating_margin("MSFT", "2025-06-30")
    assert result["error_code"] == "WORKER_FAILURE"


def test_mcp_protocol_dispatch(calc):
    pytest.importorskip("fastmcp")
    import asyncio
    from fastmcp import Client

    async def run():
        async with Client(create_server(calc)) as client:
            tools = sorted(t.name for t in await client.list_tools())
            assert tools == ["calc_status", "calculate_operating_margin", "calculate_revenue_growth"]
            margin = (await client.call_tool("calculate_operating_margin", {
                "ticker": "MSFT", "report_date": "2025-06-30"})).data
            assert margin["ok"] and margin["data"]["value_percent"] == "25.00"
            growth = (await client.call_tool("calculate_revenue_growth", {
                "ticker": "MSFT", "current_report_date": "2025-06-30",
                "prior_report_date": "2024-06-30"})).data
            assert growth["ok"] and growth["data"]["value_percent"] == "25.00"
    asyncio.run(run())

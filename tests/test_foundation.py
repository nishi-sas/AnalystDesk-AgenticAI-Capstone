from dataclasses import replace
from decimal import Decimal
import pytest
import httpx
from analyst_desk.calculations import operating_margin, FinancialDataError
from analyst_desk.sec_client import EdgarClient, EdgarError
from analyst_desk.xbrl import select_annual_fact, REVENUE_TAGS
from analyst_desk.cli import build_comparison, comparison_markdown, main


def test_ratio_calculation_and_provenance(make_fact):
    revenue = make_fact("100", concept="Revenues")
    op = make_fact("17.25", concept="OperatingIncomeLoss")
    result = operating_margin(revenue, op)
    assert result.value_percent == Decimal("17.25")
    assert result.to_dict()["operands"] == [op.fact_id, revenue.fact_id]
    assert "0000789019-25-000111" in revenue.fact_id


def test_ratio_refuses_other_periods(make_fact):
    with pytest.raises(FinancialDataError, match="different reporting periods"):
        operating_margin(make_fact(100), make_fact(10, start="2023-07-01", concept="OperatingIncomeLoss"))


def test_ratio_refuses_zero_revenue(make_fact):
    with pytest.raises(FinancialDataError, match="positive"):
        operating_margin(make_fact(0), make_fact(10, concept="OperatingIncomeLoss"))


def test_offline_cache_and_annual_filing_selection(mock_sec_cache):
    with EdgarClient(cache_dir=mock_sec_cache, offline=True) as client:
        filings = client.annual_filings("MSFT", 3)
        assert [f.report_date for f in filings] == ["2025-06-30", "2024-06-30", "2023-06-30"]
        assert filings[0].filing_url.endswith("/789019/000078901925000111/msft25.htm")


def test_missing_offline_cache_fails_cleanly(tmp_path):
    with EdgarClient(cache_dir=tmp_path, offline=True) as client:
        with pytest.raises(EdgarError, match="Offline cache miss"):
            client.ticker_to_cik("MSFT")


def test_fact_selector_does_not_confuse_comparative_year(mock_sec_cache):
    with EdgarClient(cache_dir=mock_sec_cache, offline=True) as client:
        latest, prior, _ = client.annual_filings("MSFT", 3)
        payload = client.company_facts(latest.cik)
        current_fact = select_annual_fact(payload, latest, REVENUE_TAGS)
        prior_fact = select_annual_fact(payload, prior, REVENUE_TAGS)
        assert current_fact.value == 100
        assert prior_fact.value == 80
        assert current_fact.period_end != prior_fact.period_end


def test_fact_selector_no_guess_on_missing_tag(mock_sec_cache):
    with EdgarClient(cache_dir=mock_sec_cache, offline=True) as client:
        latest = client.annual_filings("MSFT", 1)[0]
        with pytest.raises(FinancialDataError, match="No annual"):
            select_annual_fact(client.company_facts(latest.cik), latest, ("NonexistentTag",))


def test_build_comparison_offline_evidence(mock_sec_cache):
    with EdgarClient(cache_dir=mock_sec_cache, offline=True) as client:
        data = build_comparison(client, ["MSFT"], 3)
    assert len(data["companies"][0]["annual"]) == 3
    assert data["companies"][0]["annual"][-1]["operating_margin"]["value_percent"] == "25.00"
    output = comparison_markdown(data)
    assert "not yet an agent-generated" in output
    assert "SEC company facts" in output


def test_cli_returns_error_for_offline_cache_miss(tmp_path):
    assert main(["report", "--offline", "--cache", str(tmp_path), "--tickers", "MSFT"]) == 2


def test_sec_client_sends_identified_user_agent(tmp_path):
    seen = []
    def fake(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"0":{"ticker":"MSFT","cik_str":789019,"title":"Microsoft"}})
    with httpx.Client(transport=httpx.MockTransport(fake)) as mock:
        with EdgarClient(cache_dir=tmp_path, user_agent="AnalystDesk research@example.org", client=mock) as client:
            assert client.ticker_to_cik("MSFT")[0] == 789019
    assert seen[0].headers["User-Agent"] == "AnalystDesk research@example.org"
    assert (tmp_path / "company_tickers.json").exists()
    assert (tmp_path / "company_tickers.meta.json").exists()


def test_cli_creates_auditable_output(mock_sec_cache, tmp_path):
    path = tmp_path / "comparison.md"
    code = main(["report", "--offline", "--cache", str(mock_sec_cache),
                 "--tickers", "MSFT", "--years", "3", "--output", str(path)])
    assert code == 0
    assert path.exists()
    assert path.with_suffix(".json").exists()
    assert "25.00%" in path.read_text(encoding="utf-8")

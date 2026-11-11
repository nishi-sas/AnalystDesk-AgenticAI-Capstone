from decimal import Decimal
from pathlib import Path
import pytest
from analyst_desk.contracts import Filing, ReportedFact


@pytest.fixture
def sample_filing():
    return Filing("MSFT", 789019, "Microsoft Corporation", "0000789019-25-000111", "2025-07-30",
                  "2025-06-30", "msft-20250630.htm")


@pytest.fixture
def make_fact(sample_filing):
    def builder(value, *, start="2024-07-01", end="2025-06-30", ticker="MSFT", filing=None,
                concept="Revenues"):
        f = filing or sample_filing
        return ReportedFact(ticker=ticker, company=f.company, cik=f.cik, concept=concept,
                            value=Decimal(str(value)), unit="USD", period_start=start,
                            period_end=end, filing=f)
    return builder


@pytest.fixture
def mock_sec_cache(tmp_path: Path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "company_tickers.json").write_text(
        '{"0":{"cik_str":789019,"ticker":"MSFT","title":"Microsoft Corporation"}}',
        encoding="utf-8")
    submissions = root / "submissions"
    submissions.mkdir()
    submissions.joinpath("CIK0000789019.json").write_text('''{
      "name": "Microsoft Corporation", "filings": {"recent": {
      "form": ["10-K", "10-K", "10-K", "10-Q"],
      "accessionNumber": ["0000789019-25-000111", "0000789019-24-000222", "0000789019-23-000333", "0000789019-25-001444"],
      "filingDate": ["2025-07-30", "2024-07-30", "2023-07-30", "2025-10-30"],
      "reportDate": ["2025-06-30", "2024-06-30", "2023-06-30", "2025-09-30"],
      "primaryDocument": ["msft25.htm", "msft24.htm", "msft23.htm", "q.htm"]}}}''', encoding="utf-8")
    facts = root / "companyfacts"
    facts.mkdir()
    import json
    entries = []
    for year, accn, rev in [(2025,"0000789019-25-000111",100),(2024,"0000789019-24-000222",80),(2023,"0000789019-23-000333",75)]:
        entries.append({"form":"10-K", "accn":accn, "start":f"{year-1}-07-01",
                        "end":f"{year}-06-30", "fp":"FY", "val":rev})
    # Comparatives in later filings must not replace current-fiscal-year accession values.
    entries.append({"form":"10-K", "accn":"0000789019-25-000111", "start":"2023-07-01",
                    "end":"2024-06-30", "fp":"FY", "val":9999})
    op_entries = [{**entry,"val":entry["val"]*0.25} for entry in entries]
    payload = {"facts":{"us-gaap":{"Revenues":{"units":{"USD":entries}},
                                      "OperatingIncomeLoss":{"units":{"USD":op_entries}}}}}
    facts.joinpath("CIK0000789019.json").write_text(json.dumps(payload), encoding="utf-8")
    return root

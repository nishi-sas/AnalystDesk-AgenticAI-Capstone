"""Select annual XBRL facts from the exact 10-K accession and fiscal period."""
from __future__ import annotations
from datetime import date
from decimal import Decimal

from analyst_desk.contracts import Filing, ReportedFact
from analyst_desk.calculations import FinancialDataError

# Ordered preference; actual concepts are always disclosed with each selected fact.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueGoodsNet",
)
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)


def select_annual_fact(companyfacts: dict, filing: Filing,
                       candidate_concepts: tuple[str, ...]) -> ReportedFact:
    """Select annual current-year 10-K fact; reject cross-period and later-filing comparatives."""
    concepts = companyfacts.get("facts", {}).get("us-gaap", {})
    available: list[tuple[int, str, dict]] = []
    for preference, tag in enumerate(candidate_concepts):
        for entry in concepts.get(tag, {}).get("units", {}).get("USD", []):
            if entry.get("form") != "10-K" or entry.get("accn") != filing.accession:
                continue
            start, end = entry.get("start"), entry.get("end")
            if not start or not end or end != filing.report_date:
                continue
            try:
                duration_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError:
                continue
            if not 330 <= duration_days <= 380:
                continue
            if not isinstance(entry.get("val"), (float, int)):
                continue
            available.append((preference, tag, entry))
    if not available:
        raise FinancialDataError(
            f"No annual USD XBRL fact for {filing.ticker} accession={filing.accession}, "
            f"period ending {filing.report_date}; candidate tags={candidate_concepts}. "
            "Check filing tags; do not invent missing facts.")
    available.sort(key=lambda row: (row[0], row[2]["start"], row[2].get("filed", "")))
    _, tag, item = available[0]
    return ReportedFact(ticker=filing.ticker, company=filing.company, cik=filing.cik,
                        concept=tag, value=Decimal(str(item["val"])), unit="USD",
                        period_start=item["start"], period_end=item["end"], filing=filing)

"""Deterministic financial calculations. No LLM arithmetic."""
from decimal import Decimal, ROUND_HALF_UP
from analyst_desk.contracts import ReportedFact, DerivedMetric


class FinancialDataError(ValueError):
    pass


def operating_margin(revenue: ReportedFact, operating_income: ReportedFact) -> DerivedMetric:
    if revenue.ticker != operating_income.ticker or revenue.cik != operating_income.cik:
        raise FinancialDataError("Cannot combine financial facts from different companies")
    if (revenue.period_start, revenue.period_end) != (operating_income.period_start, operating_income.period_end):
        raise FinancialDataError("Cannot combine financial facts from different reporting periods")
    if revenue.filing.accession != operating_income.filing.accession:
        raise FinancialDataError("Cannot combine facts from different SEC filings")
    if revenue.unit != "USD" or operating_income.unit != "USD":
        raise FinancialDataError("Expected USD financial facts")
    if revenue.value <= 0:
        raise FinancialDataError("Revenue must be positive")
    val = ((operating_income.value / revenue.value) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return DerivedMetric(name="Operating margin", value_percent=val,
                         formula="100 * operating_income / revenue", operands=(operating_income, revenue))

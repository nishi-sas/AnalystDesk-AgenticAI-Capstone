"""Typed financial data with enough provenance to audit each output."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal


@dataclass(frozen=True)
class Filing:
    ticker: str
    cik: int
    company: str
    accession: str
    filing_date: str
    report_date: str
    primary_document: str
    form: str = "10-K"

    @property
    def filing_url(self) -> str:
        return (f"https://www.sec.gov/Archives/edgar/data/{self.cik}/"
                f"{self.accession.replace('-', '')}/{self.primary_document}")


@dataclass(frozen=True)
class ReportedFact:
    ticker: str
    company: str
    cik: int
    concept: str
    value: Decimal
    unit: str
    period_start: str
    period_end: str
    filing: Filing

    @property
    def fact_id(self) -> str:
        return (f"CIK{self.cik:010d}|{self.filing.accession}|us-gaap:{self.concept}|"
                f"{self.period_start}:{self.period_end}|{self.unit}")

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "company": self.company, "cik": self.cik,
                "concept": self.concept, "value": str(self.value), "unit": self.unit,
                "period_start": self.period_start, "period_end": self.period_end,
                "fact_id": self.fact_id, "accession": self.filing.accession,
                "filing_url": self.filing.filing_url}


@dataclass(frozen=True)
class DerivedMetric:
    name: str
    value_percent: Decimal
    formula: str
    operands: tuple[ReportedFact, ReportedFact]

    def to_dict(self) -> dict:
        return {"name": self.name, "value_percent": str(self.value_percent),
                "formula": self.formula,
                "operands": [v.fact_id for v in self.operands]}

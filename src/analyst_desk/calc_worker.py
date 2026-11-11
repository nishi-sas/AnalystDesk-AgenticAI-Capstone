"""Fixed-formula, stdlib-only child process used by Stage 3C.

No eval/exec, file reads, network operations, shell or caller-supplied code.
This is process separation, *not* an OS/container-grade security sandbox.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

DECIMALS = Decimal("0.01")
ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")
FACT_ID = re.compile(r"CIK\d{10}\|\d{10}-\d{2}-\d{6}\|us-gaap:[A-Za-z0-9]+\|\d{4}-\d\d-\d\d:\d{4}-\d\d-\d\d\|USD\Z")

class CalculationError(ValueError):
    pass


def _day(value):
    if not isinstance(value, str):
        raise CalculationError("Invalid date")
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise CalculationError("Invalid date") from exc


def _fact(value):
    if not isinstance(value, dict):
        raise CalculationError("Fact must be a dictionary")
    for field in ("ticker", "cik", "company", "concept", "value", "unit", "period_start", "period_end", "fact_id", "accession", "filing_url"):
        if field not in value:
            raise CalculationError("Missing required SEC fact field")
    if not isinstance(value["ticker"], str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", value["ticker"]):
        raise CalculationError("Invalid ticker")
    if type(value["cik"]) is not int or value["cik"] <= 0:
        raise CalculationError("Invalid CIK")
    if not isinstance(value["accession"], str) or not ACCESSION.fullmatch(value["accession"]):
        raise CalculationError("Invalid accession")
    if not isinstance(value["concept"], str) or not re.fullmatch(r"[A-Za-z0-9]+", value["concept"]):
        raise CalculationError("Invalid XBRL concept")
    if value["unit"] != "USD":
        raise CalculationError("Expected USD")
    if not isinstance(value["value"], str) or len(value["value"]) > 100:
        raise CalculationError("Invalid decimal encoding")
    try:
        amount = Decimal(value["value"])
    except (InvalidOperation, TypeError) as exc:
        raise CalculationError("Invalid decimal amount") from exc
    if not amount.is_finite() or abs(amount) > Decimal("1e30"):
        raise CalculationError("Nonfinite or excessive amount")
    start, end = _day(value["period_start"]), _day(value["period_end"])
    if start > end or not 350 <= (end - start).days + 1 <= 380:
        raise CalculationError("Not a credible annual period")
    expected = (f"CIK{value['cik']:010d}|{value['accession']}|us-gaap:{value['concept']}|"
                f"{value['period_start']}:{value['period_end']}|USD")
    if not FACT_ID.fullmatch(value["fact_id"]) or value["fact_id"] != expected:
        raise CalculationError("SEC fact ID does not match operands")
    urlprefix = (f"https://www.sec.gov/Archives/edgar/data/{value['cik']}/"
                 f"{value['accession'].replace('-', '')}/")
    if not isinstance(value["filing_url"], str) or not value["filing_url"].startswith(urlprefix):
        raise CalculationError("SEC filing URL inconsistent with fact")
    return amount, start, end


def calculate(req):
    if not isinstance(req, dict) or not isinstance(req.get("operation"), str):
        raise CalculationError("Missing operation")
    op = req["operation"]
    a, b = req.get("a"), req.get("b")
    av, astart, aend = _fact(a)
    bv, bstart, bend = _fact(b)
    if a["ticker"] != b["ticker"] or a["cik"] != b["cik"]:
        raise CalculationError("Facts from different companies")
    if op == "operating_margin":
        if a["accession"] != b["accession"] or astart != bstart or aend != bend:
            raise CalculationError("Facts have mismatched SEC accession or annual period")
        if not a["concept"].lower().startswith("operatingincome"):
            raise CalculationError("First fact is not operating income")
        if b["concept"] not in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"):
            raise CalculationError("Second fact is not annual revenue")
        if bv <= 0:
            raise CalculationError("Revenue must be positive")
        result = (Decimal(100) * av / bv).quantize(DECIMALS, rounding=ROUND_HALF_UP)
        return {"name": "operating_margin", "value_percent": str(result),
                "formula": "100 * operating_income / revenue", "operands": [a["fact_id"], b["fact_id"]],
                "source_urls": [a["filing_url"]], "ticker": a["ticker"],
                "report_date": a["period_end"], "rounding": "ROUND_HALF_UP_2DP"}
    if op == "revenue_growth_yoy":
        allowed = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
        if a["concept"] not in allowed or b["concept"] not in allowed:
            raise CalculationError("Expected revenue concepts")
        if not (aend > bend and aend.year == bend.year + 1 and 360 <= (aend - bend).days <= 373):
            raise CalculationError("Periods are not adjacent annual years")
        if astart <= bend:
            raise CalculationError("Periods overlap")
        if bv <= 0:
            raise CalculationError("Prior revenue must be positive")
        result = (Decimal(100) * (av - bv) / bv).quantize(DECIMALS, rounding=ROUND_HALF_UP)
        return {"name": "revenue_growth_yoy", "value_percent": str(result),
                "formula": "100 * (current_revenue - prior_revenue) / prior_revenue",
                "operands": [a["fact_id"], b["fact_id"]],
                "source_urls": [a["filing_url"], b["filing_url"]], "ticker": a["ticker"],
                "current_report_date": a["period_end"], "prior_report_date": b["period_end"],
                "rounding": "ROUND_HALF_UP_2DP"}
    raise CalculationError("Unsupported operation")


def main():
    try:
        raw = sys.stdin.buffer.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise CalculationError("Calculation request too large")
        request = json.loads(raw.decode("utf-8"))
        print(json.dumps({"ok": True, "data": calculate(request)}, separators=(",", ":")))
    except (CalculationError, ValueError, TypeError, KeyError, InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        # Deliberately do not echo raw user data or paths.
        print(json.dumps({"ok": False, "error_code": "CALCULATION_REJECTED", "error_message": str(exc)[:200]}))
    except Exception:
        print(json.dumps({"ok": False, "error_code": "WORKER_ERROR", "error_message": "Calculation worker failed"}))


if __name__ == "__main__":
    main()

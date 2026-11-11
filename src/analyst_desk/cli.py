"""Windows-friendly CLI: ingest authoritative SEC facts and render a verified comparison."""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from analyst_desk.calculations import FinancialDataError, operating_margin
from analyst_desk.sec_client import EdgarClient, EdgarError
from analyst_desk.xbrl import select_annual_fact, REVENUE_TAGS, OPERATING_INCOME_TAGS


def build_comparison(client: EdgarClient, tickers: list[str], years: int) -> dict:
    all_companies = []
    for ticker in tickers:
        filings = client.annual_filings(ticker, years=years)
        payload = client.company_facts(filings[0].cik)
        annual = []
        for filing in sorted(filings, key=lambda f: f.report_date):
            revenue = select_annual_fact(payload, filing, REVENUE_TAGS)
            op_income = select_annual_fact(payload, filing, OPERATING_INCOME_TAGS)
            metric = operating_margin(revenue, op_income)
            annual.append({"fiscal_period_end": filing.report_date, "filing_date": filing.filing_date,
                           "accession": filing.accession, "filing_url": filing.filing_url,
                           "revenue": revenue.to_dict(), "operating_income": op_income.to_dict(),
                           "operating_margin": metric.to_dict()})
        all_companies.append({"ticker": ticker.upper(), "company": filings[0].company,
                              "cik": filings[0].cik, "annual": annual})
    return {"title": "SEC-source-verified operating margin comparison",
            "status": "calculated_from_cached_sec_companyfacts",
            "methodology": "Annual current-fiscal-period USD figures are matched to exact 10-K accession, "
                           "reportDate and ~one-year duration; calculation is code-based; "
                           "fiscal periods are labelled rather than silently calendar-aligned.",
            "companies": all_companies}


def comparison_markdown(comparison: dict) -> str:
    lines = ["# SEC-sourced operating-margin comparison", "",
             "**Scope:** financial facts and deterministic calculations only. This is not yet an agent-generated research note.", "",
             "**Method:** " + comparison["methodology"], "",
             "| Company | Fiscal period end | Revenue (USD) | Operating income (USD) | Operating margin | SEC 10-K |",
             "|---|---|---:|---:|---:|---|"]
    for c in comparison["companies"]:
        for record in c["annual"]:
            rev, op = record["revenue"], record["operating_income"]
            margin = record["operating_margin"]["value_percent"]
            lines.append(f'| {c["ticker"]} | {record["fiscal_period_end"]} | '
                         f'{Decimal(rev["value"]):,.2f} | {Decimal(op["value"]):,.2f} | '
                         f'{margin}% | [Filing]({record["filing_url"]}) |')
    lines.extend(["", "## Fact provenance (machine-readable identifiers)", ""])
    for c in comparison["companies"]:
        for r in c["annual"]:
            lines.extend([f'### {c["ticker"]} · fiscal period ending {r["fiscal_period_end"]}',
                          f'- Revenue: `{r["revenue"]["fact_id"]}`',
                          f'- Operating income: `{r["operating_income"]["fact_id"]}`',
                          '- Derived metric: `100 * operating_income / revenue`',
                          f'- [SEC company facts](https://data.sec.gov/api/xbrl/companyfacts/CIK{c["cik"]:010d}.json)', ""])
    lines.extend(["## Interpretation limits", "",
                  "Company fiscal year-ends may differ. The adjacent rows are not necessarily comparable over "
                  "identical calendar periods. We have not made causal, valuation or investment conclusions.", "",
                  "This foundation does not yet ingest Item 1A risks, run agent workflows, or publish research notes.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Analyst Desk: SEC-financial-data foundation")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("fetch", "report"):
        p = sub.add_parser(command)
        p.add_argument("--tickers", nargs="+", default=["MSFT", "GOOGL"])
        p.add_argument("--years", type=int, default=3)
        p.add_argument("--cache", default="data/edgar_cache")
        p.add_argument("--offline", action="store_true", help="Require cached SEC responses")
    report = sub.choices["report"]
    report.add_argument("--output", default="evidence/financial_comparison.md")
    args = parser.parse_args(argv)
    if args.years < 1:
        parser.error("--years must be positive")
    try:
        with EdgarClient(cache_dir=args.cache, offline=args.offline) as client:
            if args.command == "fetch":
                for ticker in args.tickers:
                    filings = client.annual_filings(ticker, args.years)
                    companyfacts = client.company_facts(filings[0].cik)
                    print(f'{ticker.upper()}: downloaded/cached {len(filings)} 10-K references; '
                          f'{len(companyfacts.get("facts", {}).get("us-gaap", {}))} US-GAAP concepts')
                return 0
            result = build_comparison(client, args.tickers, args.years)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(comparison_markdown(result), encoding="utf-8")
            json_path = output.with_suffix(".json")
            json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"Verified comparison: {output}\nAudit JSON: {json_path}")
            for c in result["companies"]:
                for r in c["annual"]:
                    print(f'  {c["ticker"]} {r["fiscal_period_end"]}: '
                          f'{r["operating_margin"]["value_percent"]}%')
            return 0
    except (EdgarError, FinancialDataError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

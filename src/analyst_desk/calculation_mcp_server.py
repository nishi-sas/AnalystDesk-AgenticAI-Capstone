"""Stage 3C strict financial calculation MCP service (stdio)."""
from __future__ import annotations

import argparse
import sys
from analyst_desk.calculation_service import CalculationService


def create_server(calc: CalculationService):
    from fastmcp import FastMCP

    server = FastMCP("AnalystDesk SEC Financial Calculator")

    @server.tool
    def calculate_operating_margin(ticker: str, report_date: str) -> dict:
        """Verify annual SEC revenue/operating-income facts, compute 100 * operating_income / revenue."""
        return calc.calculate_operating_margin(ticker, report_date)

    @server.tool
    def calculate_revenue_growth(ticker: str, current_report_date: str,
                                 prior_report_date: str) -> dict:
        """Verify adjacent annual SEC revenue facts and compute percent YoY growth."""
        return calc.calculate_revenue_growth(ticker, current_report_date, prior_report_date)

    @server.tool
    def calc_status() -> dict:
        """Describe approved formulas, input controls and process isolation limits."""
        return calc.calc_status()

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="AnalystDesk financial calculation MCP server (stdio)")
    parser.add_argument("--cache", default="data/edgar_cache")
    args = parser.parse_args(argv)
    try:
        create_server(CalculationService(cache_dir=args.cache)).run(transport="stdio")
    except Exception as exc:
        print(f"Calculator server startup failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

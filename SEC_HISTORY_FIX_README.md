# AnalystDesk SEC historical 10-K pagination fix

This patch updates **only** `src/analyst_desk/sec_client.py::EdgarClient.annual_filings`.
It reads SEC `filings.files[]` historical continuation pages only when `filings.recent` does not supply enough distinct annual 10-K report periods. It preserves the existing `_json` rate limiter, cache-first behavior, retry handling, and identifiable SEC User-Agent. It rejects `10-K/A`, avoids duplicate fiscal years, and fails closed if the requested coverage is unavailable.

## Apply from existing `(Analystdesk)` environment, project root

1. Unzip this package into `D:\IIT-B_Agentic_Ai\Capstone\AnalystDesk` preserving `tools/` and `tests/`.
2. `python tools\apply_sec_history_fix.py`
3. `python -m pytest -q tests\test_sec_historical_submissions.py tests\test_edgar_service.py tests\test_filing_documents.py`
4. `python -m pytest -q`
5. After passing, re-run `python -m analyst_desk.filings_cli --tickers MSFT GOOGL AAPL META NVDA ORCL WMT AMZN COST TGT HD LOW --years 3`.

**Notes:** The batch downloads into the existing `data/edgar_cache` and writes the manifest only after all requested tickers finish. The command may stop if there is a different source error, in which case preserve the cache and investigate. Do **not** rebuild Docker now; download and validate all filings locally first. This does not change the hard-coded MSFT/GOOGL research/evaluation scope; generalizing that is a separate step after ingestion.

"""SEC EDGAR client: identifiable requests, cache-first, bounded retries, and provenance."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_URL = "https://data.sec.gov"


class EdgarError(RuntimeError):
    """SEC data / connectivity / configuration error."""


class EdgarClient:
    def __init__(self, cache_dir: str | Path = "data/edgar_cache", *,
                 user_agent: str | None = None, offline: bool = False,
                 requests_per_second: float = 4.0, max_retries: int = 4,
                 client: httpx.Client | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.user_agent = user_agent or os.getenv("EDGAR_USER_AGENT", "")
        self.max_retries = max_retries
        self.min_interval = 1 / requests_per_second
        self._last_request_at = 0.0
        self._client = client or httpx.Client(timeout=30, follow_redirects=True)
        self._owns_client = client is None

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *_: object) -> None:
        if self._owns_client:
            self._client.close()

    def _validate_user_agent(self) -> None:
        if not re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", self.user_agent):
            raise EdgarError("Set EDGAR_USER_AGENT to a project name and genuine contact email in .env")

    def _json(self, url: str, path: Path) -> dict[str, Any]:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise EdgarError(f"Expected JSON object in cache: {path}")
                return data
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise EdgarError(f"Invalid cache file {path}: {exc}") from exc
        if self.offline:
            raise EdgarError(f"Offline cache miss: {path} — first run 'fetch' online")
        self._validate_user_agent()
        headers = {"User-Agent": self.user_agent,
                   "Accept": "application/json", "Accept-Encoding": "gzip, deflate"}
        for attempt in range(self.max_retries + 1):
            remaining = self.min_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()
            try:
                response = self._client.get(url, headers=headers)
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After", "")
                        delay = min(float(retry_after), 30.0) if retry_after.isdigit() else min(2 ** attempt, 16)
                        time.sleep(delay)
                        continue
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise EdgarError(f"Expected object from {url}")
                raw = response.content
                path.parent.mkdir(parents=True, exist_ok=True)
                # Write cache atomically. Preserve original JSON response bytes for audit.
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(raw)
                tmp.replace(path)
                meta = {"url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(),
                        "sha256": hashlib.sha256(raw).hexdigest(), "status_code": response.status_code}
                path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                return data
            except (httpx.HTTPError, ValueError) as exc:
                if attempt >= self.max_retries:
                    raise EdgarError(f"SEC request failed ({url}): {exc}") from exc
                time.sleep(min(2 ** attempt, 16))
        raise EdgarError(f"SEC request exhausted retries: {url}")

    def ticker_to_cik(self, ticker: str) -> tuple[int, str]:
        payload = self._json(TICKER_URL, self.cache_dir / "company_tickers.json")
        wanted = ticker.strip().upper()
        for entry in payload.values():
            if entry.get("ticker", "").upper() == wanted:
                return int(entry["cik_str"]), str(entry["title"])
        raise EdgarError(f"Ticker {wanted} not found in SEC ticker mapping")

    def submissions(self, cik: int) -> dict:
        return self._json(f"{DATA_URL}/submissions/CIK{cik:010d}.json",
                          self.cache_dir / "submissions" / f"CIK{cik:010d}.json")

    def company_facts(self, cik: int) -> dict:
        return self._json(f"{DATA_URL}/api/xbrl/companyfacts/CIK{cik:010d}.json",
                          self.cache_dir / "companyfacts" / f"CIK{cik:010d}.json")

    def annual_filings(self, ticker: str, years: int = 3) -> list:
        """Return the newest distinct annual 10-Ks, consulting SEC history if needed.

        The SEC /submissions/CIK....json recent table covers a rolling window.
        Older records are in filings.files pages. Fetch only as many history
        pages as needed, using the existing cache-first/rate-limited _json.
        """
        from analyst_desk.contracts import Filing

        if type(years) is not int or years < 1:
            raise EdgarError("years must be a positive integer")
        cik, company = self.ticker_to_cik(ticker)
        payload = self.submissions(cik)
        filings_group = payload.get("filings", {})
        if not isinstance(filings_group, dict):
            raise EdgarError("Invalid SEC submissions filings object")
        company_name = payload.get("name") or company
        keys = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument")

        def read_rows(table: dict) -> list[Filing]:
            if not isinstance(table, dict):
                raise EdgarError("Invalid SEC submissions columnar table")
            forms = table.get("form", [])
            if not isinstance(forms, list):
                raise EdgarError("Invalid SEC submissions form column")
            found = []
            for idx, form in enumerate(forms):
                # Exactly 10-K: amendments are not separate annual reports.
                if form != "10-K":
                    continue
                try:
                    row = {key: table[key][idx] for key in keys}
                except (IndexError, KeyError, TypeError):
                    continue
                if not all(isinstance(row[key], str) and row[key].strip() for key in keys):
                    continue
                found.append(Filing(
                    ticker=ticker.upper(), cik=cik, company=company_name,
                    accession=row["accessionNumber"],
                    filing_date=row["filingDate"], report_date=row["reportDate"],
                    primary_document=row["primaryDocument"],
                ))
            return found

        records = read_rows(filings_group.get("recent", {}))

        def newest_unique() -> list[Filing]:
            records.sort(key=lambda v: (v.report_date, v.filing_date, v.accession), reverse=True)
            unique = {}
            for filing in records:
                unique.setdefault(filing.report_date, filing)
            return list(unique.values())[:years]

        result = newest_unique()
        if len(result) < years:
            pages = filings_group.get("files", [])
            if not isinstance(pages, list):
                raise EdgarError("Invalid SEC historical submissions index")
            # Prefer the newest historical page if several are advertised.
            pages = sorted(pages, key=lambda p: str(p.get("filingTo", "")) if isinstance(p, dict) else "", reverse=True)
            for page in pages:
                name = page.get("name") if isinstance(page, dict) else None
                # Allow only a historical SEC page for this *same* CIK;
                # never turn untrusted JSON into a URL or local filesystem path.
                if not isinstance(name, str) or re.fullmatch(
                    rf"CIK{cik:010d}-submissions-[0-9]+[.]json", name
                ) is None:
                    raise EdgarError("Invalid SEC historical submissions filename")
                history = self._json(
                    f"{DATA_URL}/submissions/{name}",
                    self.cache_dir / "submissions" / name,
                )
                records.extend(read_rows(history))
                result = newest_unique()
                if len(result) >= years:
                    break
        if len(result) < years:
            raise EdgarError(
                f"Only {len(result)} usable 10-K fiscal years for {ticker}; requested {years}. "
                "Recent and available historical SEC submission pages were checked."
            )
        return result

"""Stage 3B: source-verified, read-only SEC EDGAR/XBRL tool backend.

No arbitrary URLs, shell execution, user-provided local paths, or derived math.
Offline by default. Financial ratios belong to the separate Stage 3C sandbox.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Callable

from analyst_desk.calculations import FinancialDataError
from analyst_desk.sec_client import DATA_URL, TICKER_URL, EdgarClient, EdgarError
from analyst_desk.xbrl import OPERATING_INCOME_TAGS, REVENUE_TAGS, select_annual_fact

_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,9}\Z")
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_METRICS = {"revenue": REVENUE_TAGS, "operating_income": OPERATING_INCOME_TAGS}
_MAX_JSON_BYTES = 100 * 1024 * 1024


class InputError(ValueError):
    pass


class SourceIntegrityError(RuntimeError):
    pass


def _ticker(value: str) -> str:
    if not isinstance(value, str) or not _TICKER.fullmatch(value.strip().upper()):
        raise InputError("ticker must be a valid symbol of at most 10 characters")
    return value.strip().upper()


def _years(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise InputError("years must be an integer from 1 to 5")
    return value


def _date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InputError("report_date must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise InputError("report_date must be a valid calendar date") from exc
    return value


def _metric(value: str) -> str:
    if not isinstance(value, str) or value not in _METRICS:
        raise InputError("metric must be revenue or operating_income")
    return value


class EdgarFactsService:
    """MCP-safe facade around the existing Stage 1 SEC client and XBRL selectors.

    Cache sidecars are hashes/provenance, not cryptographic signatures. SHA-256
    detects accidental/in-place tampering, but cannot prove SEC authorship if an
    adversary can replace both the payload and sidecar. Authoritative online SEC
    transport and secure filesystem controls are still needed for authenticity.
    """

    def __init__(self, cache_dir: str | Path = "data/edgar_cache", *, offline: bool = True,
                 client_factory: Callable[..., EdgarClient] = EdgarClient) -> None:
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self._factory = client_factory

    @property
    def provenance(self) -> dict:
        return {"source": "SEC_EDGAR", "source_type": "SEC_10K_XBRL_US_GAAP",
                "cache_integrity": "SHA256_AND_URL", "offline": self.offline,
                "read_only": True}

    def _wrap(self, action) -> dict:
        start = time.perf_counter()
        try:
            result = action()
            return {"ok": True, "data": result, "error_code": None,
                    "error_message": None, "provenance": self.provenance,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
        except InputError as exc:
            code, message = "INVALID_ARGUMENT", str(exc)
        except LookupError as exc:
            code, message = "NOT_FOUND", str(exc)
        except SourceIntegrityError:
            code, message = "SOURCE_INTEGRITY_ERROR", "SEC cache checksum or source provenance validation failed"
        except FinancialDataError:
            code, message = "FACT_UNAVAILABLE", "No matching current-period annual XBRL fact; no estimate generated"
        except EdgarError:
            code, message = "SEC_DATA_ERROR", "SEC data unavailable or requested filing years are not cached; see server logs"
        except (OSError, ValueError, KeyError, TypeError):
            code, message = "SEC_DATA_ERROR", "SEC response could not be verified; see server logs"
        except Exception:
            code, message = "INTERNAL_ERROR", "EDGAR tool failed; see server logs"
        return {"ok": False, "data": None, "error_code": code,
                "error_message": message, "provenance": self.provenance,
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}

    def _verify(self, path: Path, url: str) -> dict | None:
        """Validate existing JSON against Stage 1 sidecar before reading it.

        When online and not yet cached, Stage 1 downloads the file and writes the
        sidecar; the caller then validates the new pair as well.
        """
        meta_path = path.with_suffix(".meta.json")
        if not path.exists():
            if meta_path.exists():
                raise SourceIntegrityError("Orphan SEC cache sidecar")
            return None
        if not path.is_file() or not meta_path.is_file():
            raise SourceIntegrityError("SEC cache missing provenance sidecar")
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise SourceIntegrityError("SEC cache exceeds maximum JSON size")
        try:
            raw = path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise SourceIntegrityError("SEC cache could not be decoded") from exc
        if (not isinstance(meta, dict) or meta.get("url") != url
                or meta.get("sha256") != hashlib.sha256(raw).hexdigest()
                or meta.get("status_code") != 200):
            raise SourceIntegrityError("SEC URL/status/SHA256 mismatch")
        return {"url": url, "sha256": meta["sha256"], "fetched_utc": meta.get("fetched_utc")}

    def _client(self):
        return self._factory(cache_dir=self.cache_dir, offline=self.offline)

    def _filings(self, client: EdgarClient, tick: str, years: int) -> tuple[list, list]:
        verified = []
        p = self.cache_dir / "company_tickers.json"
        self._verify(p, TICKER_URL)
        cik, _ = client.ticker_to_cik(tick)
        verified.append(self._require_verified(p, TICKER_URL))
        url = f"{DATA_URL}/submissions/CIK{cik:010d}.json"
        p = self.cache_dir / "submissions" / f"CIK{cik:010d}.json"
        self._verify(p, url)
        filings = client.annual_filings(tick, years=years)
        verified.append(self._require_verified(p, url))
        for filing in filings:
            if (not _ACCESSION.fullmatch(filing.accession) or
                not _FILENAME.fullmatch(filing.primary_document) or ".." in filing.primary_document or
                not filing.primary_document.lower().endswith((".htm", ".html"))):
                raise SourceIntegrityError("Unsafe SEC accession or primaryDocument in submissions")
        return filings, verified

    def _require_verified(self, path: Path, url: str) -> dict:
        result = self._verify(path, url)
        if result is None:
            raise SourceIntegrityError("Expected cached SEC response and metadata after read")
        return result

    def _facts(self, client: EdgarClient, cik: int, verified: list) -> dict:
        url = f"{DATA_URL}/api/xbrl/companyfacts/CIK{cik:010d}.json"
        p = self.cache_dir / "companyfacts" / f"CIK{cik:010d}.json"
        self._verify(p, url)
        facts = client.company_facts(cik)
        verified.append(self._require_verified(p, url))
        return facts

    @staticmethod
    def _filing_row(filing) -> dict:
        return {"ticker": filing.ticker, "company": filing.company, "cik": filing.cik,
                "form": filing.form, "accession": filing.accession,
                "report_date": filing.report_date, "filing_date": filing.filing_date,
                "primary_document": filing.primary_document, "filing_url": filing.filing_url,
                "untrusted_source_metadata": True}

    def list_annual_filings(self, ticker: str, years: int = 3) -> dict:
        """List exact 10-K accession/report dates from SEC submissions."""
        def work():
            tick, count = _ticker(ticker), _years(years)
            with self._client() as client:
                filings, verified = self._filings(client, tick, count)
                return {"ticker": tick, "filings": [self._filing_row(f) for f in filings],
                        "count": len(filings), "source_files": verified}
        return self._wrap(work)

    def get_annual_facts(self, ticker: str, years: int = 3) -> dict:
        """Return *reported* revenue and operating income; never calculate a ratio."""
        def work():
            tick, count = _ticker(ticker), _years(years)
            with self._client() as client:
                filings, verified = self._filings(client, tick, count)
                company_facts = self._facts(client, filings[0].cik, verified)
                annual = []
                for filing in sorted(filings, key=lambda f: f.report_date):
                    rev = select_annual_fact(company_facts, filing, REVENUE_TAGS)
                    operating = select_annual_fact(company_facts, filing, OPERATING_INCOME_TAGS)
                    annual.append({"filing": self._filing_row(filing),
                                   "revenue": rev.to_dict(), "operating_income": operating.to_dict()})
                return {"ticker": tick, "annual": annual, "count": len(annual),
                        "calculation_performed": False, "source_files": verified}
        return self._wrap(work)

    def get_annual_fact(self, ticker: str, report_date: str,
                        metric: str, years: int = 3) -> dict:
        """Retrieve a single USD fact matched to the *exact* 10-K accession and FY."""
        def work():
            tick, day, name, count = _ticker(ticker), _date(report_date), _metric(metric), _years(years)
            with self._client() as client:
                filings, verified = self._filings(client, tick, count)
                match = next((f for f in filings if f.report_date == day), None)
                if match is None:
                    raise LookupError("No 10-K matching requested fiscal end in selected years")
                company_facts = self._facts(client, match.cik, verified)
                fact = select_annual_fact(company_facts, match, _METRICS[name])
                return {"metric": name, "fact": fact.to_dict(), "filing": self._filing_row(match),
                        "calculation_performed": False, "source_files": verified}
        return self._wrap(work)

    def edgar_status(self) -> dict:
        """Report cache coverage without reading arbitrary files or contacting SEC."""
        def work():
            root = self.cache_dir
            return {"offline": self.offline, "read_only": True,
                    "cache": {"ticker_map_present": (root / "company_tickers.json").is_file(),
                              "submissions_count": sum(not f.name.endswith(".meta.json") for f in (root / "submissions").glob("CIK*.json")),
                              "companyfacts_count": sum(not f.name.endswith(".meta.json") for f in (root / "companyfacts").glob("CIK*.json"))},
                    "metrics": sorted(_METRICS), "max_years_per_call": 5}
        return self._wrap(work)

"""Stage 2A: retrieve the exact source 10-K HTML, with auditable local caching.

This stage intentionally does not parse or index HTML. It verifies source acquisition
before later Item 1A / Item 7 / Item 8 extraction and hybrid retrieval.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from analyst_desk.contracts import Filing
from analyst_desk.sec_client import EdgarClient, EdgarError

MAX_HTML_BYTES = 30 * 1024 * 1024
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _document_path(cache_dir: Path, filing: Filing) -> Path:
    """Build a safe cache path from SEC-sourced identifiers."""
    name = filing.primary_document
    if (not _FILENAME.fullmatch(name) or ".." in name or
            Path(name).suffix.lower() not in (".htm", ".html")):
        raise EdgarError(f"Unsafe/non-HTML SEC primary document filename: {name!r}")
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", filing.accession):
        raise EdgarError(f"Unexpected SEC accession number: {filing.accession!r}")
    return cache_dir / "documents" / f"CIK{filing.cik:010d}" / filing.accession.replace("-", "") / name


def download_filing_html(sec: EdgarClient, filing: Filing,
                         max_bytes: int = MAX_HTML_BYTES) -> tuple[Path, dict]:
    """Fetch/cached exact SEC 10-K source; retain accession/date/hash provenance.

    The SEC hostname is hard-coded by the Filing.filing_url property, and rechecked.
    All downloaded data is treated as *untrusted content* in later stages.
    """
    if filing.form != "10-K":
        raise EdgarError(f"Expected 10-K, got {filing.form!r}")
    path = _document_path(sec.cache_dir, filing)
    meta_path = path.with_name(path.name + ".meta.json")
    url = filing.filing_url
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.sec.gov" or
            not parsed.path.startswith("/Archives/edgar/data/")):
        raise EdgarError(f"Unexpected document URL: {url}")

    if path.is_file():
        if not meta_path.is_file():
            raise EdgarError(f"Document cache exists without provenance metadata: {path}")
        raw = path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta.get("sha256") != hashlib.sha256(raw).hexdigest() or
                meta.get("url") != url or meta.get("accession") != filing.accession):
            raise EdgarError(f"Cached document does not match its provenance metadata: {path}")
        meta = dict(meta, cache_hit=True)
        return path, meta

    if sec.offline:
        raise EdgarError(f"Offline 10-K HTML cache miss: {path}")
    sec._validate_user_agent()
    headers = {"User-Agent": sec.user_agent, "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip, deflate"}
    last_error = None
    for attempt in range(sec.max_retries + 1):
        remaining = sec.min_interval - (time.monotonic() - sec._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        sec._last_request_at = time.monotonic()
        try:
            # Streaming permits us to enforce the hard download size limit.
            with sec._client.stream("GET", url, headers=headers) as response:
                if response.status_code in (429, 500, 502, 503, 504) and attempt < sec.max_retries:
                    delay = min(2 ** attempt, 16)
                    header = response.headers.get("Retry-After", "")
                    if header.isdigit():
                        delay = min(int(header), 30)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                if response.url.host != "www.sec.gov":
                    raise EdgarError(f"Redirected outside sec.gov: {response.url}")
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise EdgarError(f"10-K HTML exceeded {max_bytes} bytes: {url}")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            if not raw.strip() or b"<html" not in raw[:2500].lower() and b"<!doctype html" not in raw[:2500].lower():
                raise EdgarError(f"SEC response was not recognisable HTML: {url}")
            meta = {"ticker": filing.ticker, "cik": filing.cik, "form": filing.form,
                    "accession": filing.accession, "report_date": filing.report_date,
                    "filing_date": filing.filing_date, "primary_document": filing.primary_document,
                    "url": url, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    "downloaded_utc": datetime.now(timezone.utc).isoformat()}
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".tmp")
            temp.write_bytes(raw)
            temp.replace(path)
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return path, dict(meta, cache_hit=False)
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            if attempt < sec.max_retries:
                time.sleep(min(2 ** attempt, 16))
                continue
    raise EdgarError(f"Could not retrieve SEC HTML {url}: {last_error}")

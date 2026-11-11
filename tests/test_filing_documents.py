"""Stage 2A download tests use mocked HTTP responses; never depend on live SEC."""
from dataclasses import replace
import hashlib
import json

import httpx
import pytest

from analyst_desk.contracts import Filing
from analyst_desk.filing_documents import download_filing_html
from analyst_desk.filings_cli import main
from analyst_desk.sec_client import EdgarClient, EdgarError

HTML = b"<!DOCTYPE html><html><head><title>10-K test fixture</title></head><body>Item 1A Risk factors</body></html>"


def test_html_download_caches_hash_and_exact_accession(tmp_path, sample_filing):
    calls = []
    def route(request):
        calls.append(request)
        return httpx.Response(200, content=HTML, headers={"Content-Type": "text/html"})
    with httpx.Client(transport=httpx.MockTransport(route)) as mocked:
        with EdgarClient(cache_dir=tmp_path, user_agent="AnalystDesk test@example.org", client=mocked) as sec:
            path, meta = download_filing_html(sec, sample_filing)
            assert path.is_file()
            assert meta["sha256"] == hashlib.sha256(HTML).hexdigest()
            assert meta["accession"] == sample_filing.accession
            assert meta["report_date"] == "2025-06-30"
            assert meta["cache_hit"] is False
            again, cached = download_filing_html(sec, sample_filing)
            assert again == path
            assert cached["cache_hit"] is True
    assert len(calls) == 1
    assert calls[0].url.host == "www.sec.gov"
    assert calls[0].headers["User-Agent"] == "AnalystDesk test@example.org"


def test_offline_document_without_cache_is_error(tmp_path, sample_filing):
    with EdgarClient(cache_dir=tmp_path, offline=True) as sec:
        with pytest.raises(EdgarError, match="Offline 10-K HTML cache miss"):
            download_filing_html(sec, sample_filing)


def test_reject_path_traversal_filename(tmp_path, sample_filing):
    poisoned = replace(sample_filing, primary_document="../../private.txt")
    with EdgarClient(cache_dir=tmp_path, offline=True) as sec:
        with pytest.raises(EdgarError, match="Unsafe/non-HTML"):
            download_filing_html(sec, poisoned)


def test_reject_wrong_document_type(tmp_path, sample_filing):
    def route(request):
        return httpx.Response(200, content=b"Not an SEC filing", headers={"Content-Type": "text/plain"})
    with httpx.Client(transport=httpx.MockTransport(route)) as mocked:
        with EdgarClient(cache_dir=tmp_path, user_agent="AnalystDesk test@example.org", client=mocked) as sec:
            with pytest.raises(EdgarError, match="not recognisable HTML"):
                download_filing_html(sec, sample_filing)


def test_refuse_tampered_html_cache(tmp_path, sample_filing):
    def route(request):
        return httpx.Response(200, content=HTML)
    with httpx.Client(transport=httpx.MockTransport(route)) as mocked:
        with EdgarClient(cache_dir=tmp_path, user_agent="AnalystDesk test@example.org", client=mocked) as sec:
            path, _ = download_filing_html(sec, sample_filing)
            path.write_bytes(HTML + b"BAD")
            with pytest.raises(EdgarError, match="does not match"):
                download_filing_html(sec, sample_filing)

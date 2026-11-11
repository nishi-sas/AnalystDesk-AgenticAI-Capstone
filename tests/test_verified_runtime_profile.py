"""Opt-in verified-profile security and compatibility tests (offline only)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analyst_desk.verified_runtime_profile import (
    PROFILE_ENV, VerifiedProfileError, knowledge_base_paths,
    load_verified_profile, permitted_company_tickers,
)

RID = "20261101T100701Z_1219a55c"
TICKERS = ("MSFT", "GOOGL", "AAPL", "META", "ADBE", "CRM",
           "TGT", "HD", "LOW", "BBY", "DG", "ULTA")


def make_release(root: Path, *, drop=None, duplicate=False, bad_text=False) -> Path:
    release = root / "data" / "verified_coverage" / "runs" / RID
    release.mkdir(parents=True)
    (release / "hybrid_index").mkdir()
    with (release / "10k_verified_passages.jsonl").open("w", encoding="utf-8") as dest:
        for ticker in TICKERS:
            for date in ("2023-12-31", "2024-12-31", "2025-12-31"):
                for item in ("1A", "7", "8"):
                    if (ticker, date, item) == drop:
                        continue
                    rec = {"ticker":ticker,"report_date":date,"item":item,
                           "passage_id":f"{ticker}_{date}_Item{item}_00001",
                           "source_sha256":"a"*64,"source_url":"https://www.sec.gov/Archives/example.htm",
                           "text":"SEC verified source passage"}
                    if bad_text and ticker == "GOOGL" and item == "8":
                        rec["text"] = "Bad \ufffd text"
                    dest.write(json.dumps(rec) + "\n")
                    if duplicate and ticker == "MSFT" and item == "8":
                        dest.write(json.dumps(rec) + "\n")
    return release


def test_default_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    assert load_verified_profile(tmp_path) is None
    assert permitted_company_tickers(tmp_path, ("MSFT", "GOOGL")) == ("MSFT", "GOOGL")
    assert knowledge_base_paths(tmp_path) == (
        tmp_path / "data/parsed/10k_passages.jsonl",
        tmp_path / "data/retrieval_index")


def test_pinned_profile_sets_data_and_planner_together(tmp_path, monkeypatch):
    make_release(tmp_path)
    monkeypatch.setenv(PROFILE_ENV, RID)
    profile = load_verified_profile(tmp_path)
    assert profile is not None and profile.passages == 108
    assert profile.tickers == tuple(sorted(TICKERS))
    assert knowledge_base_paths(tmp_path) == (profile.corpus, profile.index)
    assert permitted_company_tickers(tmp_path, ("MSFT", "GOOGL")) == profile.tickers


@pytest.mark.parametrize("value", ("../escape", "", "20261101T100701Z_1219a55c/../../", "latest", "x"))
def test_bad_or_absent_release_cannot_escape(tmp_path, monkeypatch, value):
    make_release(tmp_path)
    if not value:
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        assert load_verified_profile(tmp_path) is None
    else:
        monkeypatch.setenv(PROFILE_ENV, value)
        with pytest.raises(VerifiedProfileError):
            load_verified_profile(tmp_path)


def test_missing_item_fails_closed(tmp_path, monkeypatch):
    make_release(tmp_path, drop=("GOOGL", "2025-12-31", "8"))
    monkeypatch.setenv(PROFILE_ENV, RID)
    with pytest.raises(VerifiedProfileError, match="12 companies"):
        load_verified_profile(tmp_path)


def test_duplicate_passage_id_fails_closed(tmp_path, monkeypatch):
    make_release(tmp_path, duplicate=True)
    monkeypatch.setenv(PROFILE_ENV, RID)
    with pytest.raises(VerifiedProfileError, match="structural"):
        load_verified_profile(tmp_path)


def test_bad_character_fails_closed(tmp_path, monkeypatch):
    make_release(tmp_path, bad_text=True)
    monkeypatch.setenv(PROFILE_ENV, RID)
    with pytest.raises(VerifiedProfileError, match="structural"):
        load_verified_profile(tmp_path)


def test_missing_index_fails_closed(tmp_path, monkeypatch):
    release = make_release(tmp_path)
    (release / "hybrid_index").rmdir()
    monkeypatch.setenv(PROFILE_ENV, RID)
    with pytest.raises(VerifiedProfileError, match="missing/unsafe"):
        load_verified_profile(tmp_path)

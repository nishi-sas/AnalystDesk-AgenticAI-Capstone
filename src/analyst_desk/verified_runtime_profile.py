"""Opt-in, release-pinned Stage 4A/4B knowledge-base profile.

The unset environment variable preserves the original MSFT/GOOGL defaults.
Only published, local, immutable-by-convention verified-coverage runs qualify.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PROFILE_ENV = "ANALYSTDESK_VERIFIED_RELEASE_ID"
_RELEASE_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z_[a-f0-9]{8}\Z")
_TICKER_RE = re.compile(r"[A-Z]{2,6}\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_ITEMS = frozenset(("1A", "7", "8"))


class VerifiedProfileError(ValueError):
    """Expanded release is absent, incomplete, malformed or outside its allowed root."""


@dataclass(frozen=True)
class Profile:
    release_id: str
    corpus: Path
    index: Path
    tickers: tuple[str, ...]
    passages: int


def selected_release_id() -> str | None:
    """Never use a moving 'latest' pointer for live, approved research workflows."""
    value = os.getenv(PROFILE_ENV, "")
    if not value:
        return None
    if not _RELEASE_RE.fullmatch(value):
        raise VerifiedProfileError("Invalid pinned verified-coverage release ID")
    return value


def load_verified_profile(root: Path) -> Profile | None:
    release_id = selected_release_id()
    if release_id is None:
        return None
    project = Path(root).resolve()
    base = (project / "data" / "verified_coverage" / "runs").resolve()
    if not base.is_relative_to(project):
        raise VerifiedProfileError("Verified release root escapes the project directory")
    release = (base / release_id).resolve()
    if not release.is_relative_to(base) or not release.is_dir():
        raise VerifiedProfileError("Published verified release missing or outside release root")
    corpus = (release / "10k_verified_passages.jsonl").resolve()
    index = (release / "hybrid_index").resolve()
    if (not corpus.is_relative_to(release) or not index.is_relative_to(release)
            or not corpus.is_file() or not index.is_dir()):
        raise VerifiedProfileError("Verified corpus or retrieval index missing/unsafe")
    if corpus.stat().st_size > 100_000_000:
        raise VerifiedProfileError("Verified corpus exceeds bounded maximum")

    # This is a structural gate, not an independent assessment of SEC content.
    seen_ids: set[str] = set()
    coverage: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    passage_count = 0
    with corpus.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                raise VerifiedProfileError("Blank record in verified corpus")
            try:
                rec = json.loads(line)
                ticker, date, item = rec["ticker"], rec["report_date"], rec["item"]
                passage_id, source_sha = rec["passage_id"], rec["source_sha256"]
            except (KeyError, TypeError, ValueError) as exc:
                raise VerifiedProfileError("Malformed verified-corpus record") from exc
            if (not isinstance(ticker, str) or not _TICKER_RE.fullmatch(ticker)
                    or not isinstance(date, str) or not _DATE_RE.fullmatch(date)
                    or item not in _ITEMS
                    or not isinstance(passage_id, str) or not passage_id
                    or passage_id in seen_ids
                    or not isinstance(source_sha, str) or not _SHA_RE.fullmatch(source_sha)
                    or not isinstance(rec.get("text"), str) or not rec["text"].strip()
                    or "\ufffd" in rec["text"]
                    or not isinstance(rec.get("source_url"), str)
                    or not rec["source_url"].startswith("https://www.sec.gov/Archives/")):
                raise VerifiedProfileError("Verified-corpus structural/provenance check failed")
            seen_ids.add(passage_id)
            coverage[ticker][date].add(item)
            passage_count += 1
    if (len(coverage) != 12 or sum(map(len, coverage.values())) != 36
            or any(len(periods) != 3 or any(items != _ITEMS for items in periods.values())
                   for periods in coverage.values())):
        raise VerifiedProfileError("Verified release must contain 12 companies, 36 filing periods and Items 1A/7/8")
    return Profile(release_id, corpus, index, tuple(sorted(coverage)), passage_count)


def knowledge_base_paths(root: Path) -> tuple[Path, Path]:
    profile = load_verified_profile(root)
    if profile is None:
        root = Path(root)
        return root / "data/parsed/10k_passages.jsonl", root / "data/retrieval_index"
    return profile.corpus, profile.index


def permitted_company_tickers(root: Path, legacy: tuple[str, ...]) -> tuple[str, ...]:
    profile = load_verified_profile(root)
    return profile.tickers if profile is not None else legacy

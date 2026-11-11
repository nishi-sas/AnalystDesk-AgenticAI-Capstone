"""Stage 3A: read-only, source-grounded filings knowledge service.

Consumes the unchanged Stage 2B canonical corpus and Stage 2C local hybrid index.
Filing content is untrusted evidence, never instructions. No external write tools.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from analyst_desk.retrieval import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANKER_MODEL,
    CrossEncoderReranker,
    RetrievalError,
    SentenceEmbedder,
    hybrid_search,
    load_index,
    load_passages,
)

_TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}\Z")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_ID_RE = re.compile(r"[A-Za-z0-9_.\-#]{1,180}\Z")
_ITEMS = frozenset({"1A", "7", "8"})
_ITEM_TITLES = {"1A": "Risk Factors", "7": "Management's Discussion and Analysis", "8": "Financial Statements"}


class InputError(ValueError):
    """Invalid tool request that must not reach retrieval or file IO."""


def _ticker(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise InputError("ticker is required")
        return None
    if not isinstance(value, str) or not _TICKER_RE.fullmatch(value.strip().upper()):
        raise InputError("ticker must be a valid exchange symbol of at most 10 characters")
    return value.strip().upper()


def _item(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise InputError("item is required (1A, 7 or 8)")
        return None
    if not isinstance(value, str) or value.strip().upper() not in _ITEMS:
        raise InputError("item must be 1A, 7 or 8")
    return value.strip().upper()


def _report_date(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise InputError("report_date must use YYYY-MM-DD")
    from datetime import date
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise InputError("report_date must be a valid calendar date") from exc
    return value


def _number(value: int, name: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InputError(f"{name} must be an integer from {low} to {high}")
    return value


class FilingsKnowledgeBase:
    """In-memory cache + query backend with deterministic failure envelopes.

    Loads/validates the corpus and index eagerly. Models load lazily for searches.
    This class is also directly unit-testable without FastMCP or model downloads.
    """

    def __init__(
        self,
        corpus: str | Path = "data/parsed/10k_passages.jsonl",
        index_dir: str | Path = "data/retrieval_index",
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        embedder_factory: Callable[[], Any] | None = None,
        reranker_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.index = load_index(index_dir, corpus=corpus, expected_model=model_name)
        self.passages = load_passages(corpus)
        self.by_id = {p["passage_id"]: p for p in self.passages}
        missing = {r["passage_id"] for r in self.index.records} - self.by_id.keys()
        if missing:
            raise RetrievalError("Index references passages absent from canonical corpus")
        self._embedder_factory = embedder_factory or (lambda: SentenceEmbedder(model_name))
        self._reranker_factory = reranker_factory or (lambda: CrossEncoderReranker(DEFAULT_RERANKER_MODEL))
        self._embedder: Any | None = None
        self._reranker: Any | None = None
        self._model_init_lock = Lock()
        self._filings: dict[tuple[str, str, str], dict] = {}
        for p in self.passages:
            key = (p["ticker"], p["report_date"], p["accession"])
            info = self._filings.setdefault(key, {
                "ticker": p["ticker"], "report_date": p["report_date"],
                "accession": p["accession"], "source_url": p["source_url"],
                "items": defaultdict(int),
            })
            if p["source_url"] != info["source_url"]:
                raise RetrievalError("Conflicting source URLs for one filing")
            info["items"][p["item"]] += 1

    @property
    def provenance(self) -> dict:
        return {"corpus_sha256": self.index.manifest["corpus_sha256"],
                "embedding_model": self.index.manifest["embedding_model"],
                "index_format_version": self.index.manifest["format_version"],
                "source_type": "SEC_EDGAR_10K"}

    def _wrap(self, fn: Callable[[], Any]) -> dict:
        start = time.perf_counter()
        try:
            data = fn()
            return {"ok": True, "data": data, "error_code": None,
                    "error_message": None, "provenance": self.provenance,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
        except InputError as exc:
            code, message = "INVALID_ARGUMENT", str(exc)
        except LookupError as exc:
            code, message = "NOT_FOUND", str(exc)
        except (RetrievalError, OSError, KeyError, ValueError) as exc:
            code, message = "RETRIEVAL_ERROR", str(exc)
        except Exception:
            # Do not leak credentials, local file paths or model internals to tools.
            code, message = "INTERNAL_ERROR", "KB operation failed; inspect server diagnostics"
        return {"ok": False, "data": None, "error_code": code,
                "error_message": message, "provenance": self.provenance,
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}

    def _models(self, *, rerank: bool) -> tuple[Any, Any | None]:
        # Synchronize lazy model creation for parallel research branches.
        with self._model_init_lock:
            if self._embedder is None:
                self._embedder = self._embedder_factory()
            if self._embedder.model_name != self.index.manifest["embedding_model"]:
                raise RetrievalError("Loaded model differs from indexed embedding model")
            if rerank and self._reranker is None:
                self._reranker = self._reranker_factory()
            return self._embedder, self._reranker if rerank else None

    def search_passages(self, query: str, ticker: str | None = None,
                        item: str | None = None, report_date: str | None = None,
                        top_n: int = 5, rerank: bool = True) -> dict:
        """Hybrid BM25 + vector + RRF search; optional cross-encoder rerank."""
        def work():
            if not isinstance(query, str) or not 3 <= len(query.strip()) <= 500:
                raise InputError("query must contain 3–500 characters")
            tick, section, date = _ticker(ticker), _item(item), _report_date(report_date)
            count = _number(top_n, "top_n", low=1, high=10)
            if not isinstance(rerank, bool):
                raise InputError("rerank must be a boolean")
            # No model download for impossible metadata filters.
            if not any((tick is None or p["ticker"] == tick)
                       and (section is None or p["item"] == section)
                       and (date is None or p["report_date"] == date)
                       for p in self.passages):
                return {"query": query.strip(), "filters": {"ticker": tick, "item": section,
                        "report_date": date}, "reranked": rerank, "hits": [], "count": 0}
            embedder, cross = self._models(rerank=rerank)
            hits = hybrid_search(self.index, query.strip(), embedder, ticker=tick,
                                 item=section, report_date=date, top_n=count,
                                 candidate_k=max(30, count), reranker=cross)
            output = []
            for h in hits:
                output.append({
                    "passage_id": h["passage_id"], "search_id": h["search_id"],
                    "ticker": h["ticker"], "item": h["item"],
                    "report_date": h["report_date"], "accession": h["accession"],
                    "source_url": h["source_url"], "source_sha256": h["source_sha256"],
                    "is_table": h["is_table"], "row_start": h["row_start"], "row_end": h["row_end"],
                    "snippet": h["text"][:600], "rrf_score": h["rrf_score"],
                    "rerank_score": h["rerank_score"],
                    "untrusted_source_text": True,
                })
            return {"query": query.strip(), "filters": {"ticker": tick, "item": section,
                    "report_date": date}, "reranked": rerank, "hits": output,
                    "count": len(output)}
        return self._wrap(work)

    def get_passage(self, passage_id: str) -> dict:
        """Return the entire immutable canonical passage identified by retrieval."""
        def work():
            if not isinstance(passage_id, str) or not _ID_RE.fullmatch(passage_id):
                raise InputError("Invalid canonical passage_id")
            if passage_id not in self.by_id:
                raise LookupError("Canonical passage does not exist in the indexed corpus")
            p = self.by_id[passage_id]
            return {"passage_id": p["passage_id"], "text": p["text"],
                    "ticker": p["ticker"], "item": p["item"],
                    "accession": p["accession"], "report_date": p["report_date"],
                    "source_url": p["source_url"], "source_sha256": p["source_sha256"],
                    "is_table": p["is_table"], "untrusted_source_text": True}
        return self._wrap(work)

    def get_item_sections(self, ticker: str, item: str, report_date: str | None = None,
                          offset: int = 0, limit: int = 20) -> dict:
        """List paginated passage IDs for a specific filing section, never fabricate text."""
        def work():
            tick = _ticker(ticker, required=True)
            section = _item(item, required=True)
            date = _report_date(report_date)
            skip = _number(offset, "offset", low=0, high=100000)
            take = _number(limit, "limit", low=1, high=50)
            matched = [p for p in self.passages if p["ticker"] == tick
                       and p["item"] == section
                       and (date is None or p["report_date"] == date)]
            if not matched:
                raise LookupError("Requested SEC section is not present in the indexed corpus")
            selected = matched[skip:skip + take]
            return {"ticker": tick, "item": section, "title": _ITEM_TITLES[section],
                    "report_date": date, "total_passages": len(matched),
                    "offset": skip, "limit": take,
                    "next_offset": skip + take if skip + take < len(matched) else None,
                    "passages": [{"passage_id": p["passage_id"], "report_date": p["report_date"],
                                  "accession": p["accession"], "source_url": p["source_url"],
                                  "is_table": p["is_table"], "snippet": p["text"][:240],
                                  "untrusted_source_text": True} for p in selected]}
        return self._wrap(work)

    def kb_status(self) -> dict:
        """Expose indexed coverage and manifest without loading model weights."""
        def work():
            filings = [{**{k: v for k, v in f.items() if k != "items"},
                        "item_passage_counts": dict(f["items"])}
                       for f in self._filings.values()]
            return {"passage_count": len(self.passages),
                    "search_record_count": len(self.index.records),
                    "filings": sorted(filings, key=lambda r: (r["ticker"], r["report_date"])),
                    "read_only": True}
        return self._wrap(work)

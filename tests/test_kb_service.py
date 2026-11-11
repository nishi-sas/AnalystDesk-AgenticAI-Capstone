"""Stage 3A core contract tests: no external APIs, MCP runtime or model downloads."""
from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest

from analyst_desk.kb_service import FilingsKnowledgeBase
from analyst_desk.kb_mcp_server import create_server
from analyst_desk.retrieval import RetrievalError, build_index


class FixedEmbeddings:
    model_name = "deterministic-fixture-1"
    words = ("risk", "cyber", "revenue", "advertising", "profit", "income")

    def encode(self, texts):
        return np.array([[float(text.lower().count(w)) for w in self.words]
                         for text in texts], dtype=np.float32)


class FixedReranker:
    def score(self, query, texts):
        return [10.0 if "cyber" in text.lower() else 0.0 for text in texts]


@pytest.fixture
def kb(tmp_path):
    corpus = tmp_path / "data.jsonl"
    examples = [
        ("MSFT_2026-06-30_Item1A_00001", "MSFT", "1A", "2026-06-30", "Cyber risk from external attackers."),
        ("MSFT_2026-06-30_Item1A_00002", "MSFT", "1A", "2026-06-30", "Operating and business risks."),
        ("MSFT_2026-06-30_Item7_00001", "MSFT", "7", "2026-06-30", "Operating revenue and income."),
        ("GOOGL_2025-12-31_Item1A_00001", "GOOGL", "1A", "2025-12-31", "Advertising risk from competition."),
        ("GOOGL_2025-12-31_Item8_00001", "GOOGL", "8", "2025-12-31", "| Name | Income |\n| Advertising | Revenue |"),
    ]
    docs = [{"passage_id": pid, "ticker": ticker, "item": item,
             "report_date": date, "accession": "0000123456789", "source_url":
             "https://www.sec.gov/Archives/edgar/data/1/0000123456789/form10k.htm",
             "source_sha256": "a" * 64, "is_table": item == "8", "text": text}
            for pid, ticker, item, date, text in examples]
    corpus.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
    index_dir = tmp_path / "index"
    build_index(corpus, index_dir, FixedEmbeddings())
    counter = {"embedder": 0, "reranker": 0}

    def new_embedder():
        counter["embedder"] += 1
        return FixedEmbeddings()

    def new_reranker():
        counter["reranker"] += 1
        return FixedReranker()

    service = FilingsKnowledgeBase(corpus, index_dir,
                                   model_name=FixedEmbeddings.model_name,
                                   embedder_factory=new_embedder,
                                   reranker_factory=new_reranker)
    return service, counter, corpus, index_dir


def test_status_is_read_only_and_has_coverage(kb):
    service, count, _, _ = kb
    result = service.kb_status()
    assert result["ok"] and result["error_code"] is None
    assert result["data"]["read_only"] is True
    assert result["data"]["passage_count"] == 5
    assert len(result["data"]["filings"]) == 2
    assert result["provenance"]["source_type"] == "SEC_EDGAR_10K"
    assert count == {"embedder": 0, "reranker": 0}


def test_hybrid_search_returns_provenance_and_correct_filters(kb):
    service, _, _, _ = kb
    result = service.search_passages("cyber risk", ticker="msft", item="1a", rerank=True)
    assert result["ok"]
    assert result["data"]["hits"]
    assert all(h["ticker"] == "MSFT" and h["item"] == "1A" for h in result["data"]["hits"])
    assert all(h["source_url"].startswith("https://www.sec.gov/") for h in result["data"]["hits"])
    assert all(h["rerank_score"] is not None for h in result["data"]["hits"])
    assert all(h["untrusted_source_text"] for h in result["data"]["hits"])
    assert result["data"]["hits"][0]["passage_id"].endswith("00001")


def test_models_are_loaded_lazily_and_reused(kb):
    service, counter, _, _ = kb
    assert counter == {"embedder": 0, "reranker": 0}
    a = service.search_passages("cyber risk", ticker="MSFT", rerank=False)
    assert a["ok"] and counter == {"embedder": 1, "reranker": 0}
    b = service.search_passages("cyber risk", ticker="MSFT", rerank=True)
    assert b["ok"] and counter == {"embedder": 1, "reranker": 1}
    c = service.search_passages("cyber risk", ticker="MSFT", rerank=True)
    assert c["ok"] and counter == {"embedder": 1, "reranker": 1}


def test_get_passage_returns_canonical_not_table_window(kb):
    service, _, _, _ = kb
    result = service.get_passage("GOOGL_2025-12-31_Item8_00001")
    assert result["ok"]
    assert result["data"]["is_table"]
    assert "| Advertising | Revenue |" in result["data"]["text"]
    assert result["data"]["accession"] and result["data"]["source_sha256"]


def test_get_item_sections_paginates_without_truncation(kb):
    service, _, _, _ = kb
    first = service.get_item_sections("msft", "1A", limit=1)
    second = service.get_item_sections("MSFT", "1A", offset=1, limit=1)
    assert first["ok"] and second["ok"]
    assert first["data"]["total_passages"] == 2
    assert first["data"]["next_offset"] == 1
    assert second["data"]["next_offset"] is None
    assert first["data"]["passages"][0]["passage_id"] != second["data"]["passages"][0]["passage_id"]


@pytest.mark.parametrize("params", [
    {"query": ""}, {"query": "ab"}, {"query": "z" * 501},
    {"query": "risk", "ticker": "../secrets"},
    {"query": "risk", "item": "9"},
    {"query": "risk", "report_date": "2026-02-31"},
    {"query": "risk", "top_n": 11},
    {"query": "risk", "top_n": True},
    {"query": "risk", "rerank": "false"},
])
def test_invalid_search_fails_with_structured_error(kb, params):
    service, _, _, _ = kb
    response = service.search_passages(**params)
    assert response["ok"] is False and response["data"] is None
    assert response["error_code"] == "INVALID_ARGUMENT"
    assert isinstance(response["error_message"], str)


def test_nonexistent_filter_is_safe_empty_without_model_loading(kb):
    service, counter, _, _ = kb
    res = service.search_passages("investment risk", ticker="TSLA")
    assert res["ok"] and res["data"]["hits"] == []
    assert counter == {"embedder": 0, "reranker": 0}


def test_bad_passage_ids_rejected_and_missing_id_distinguished(kb):
    service, _, _, _ = kb
    assert service.get_passage("../../.env")["error_code"] == "INVALID_ARGUMENT"
    assert service.get_passage("UNKNOWN_ITEM_123")["error_code"] == "NOT_FOUND"


def test_section_unknown_returns_not_found(kb):
    service, _, _, _ = kb
    assert service.get_item_sections("GOOGL", "7")["error_code"] == "NOT_FOUND"
    assert service.get_item_sections("MSFT", "9")["error_code"] == "INVALID_ARGUMENT"
    assert service.get_item_sections("MSFT", "1A", limit=0)["error_code"] == "INVALID_ARGUMENT"


def test_stale_corpus_blocked_on_service_startup(kb):
    service, _, corpus, index_dir = kb
    corpus.write_text(corpus.read_text() + "\n", encoding="utf-8")
    with pytest.raises(RetrievalError, match="changed"):
        FilingsKnowledgeBase(corpus, index_dir, model_name=FixedEmbeddings.model_name)


def test_discovered_tool_names_and_dispatch_via_fake_protocol(kb, monkeypatch):
    """Registration check independent of optional FastMCP package. Not a wire test."""
    class FakeFastMCP:
        def __init__(self, name):
            self.name = name
            self.registered = {}
        def tool(self, function):
            self.registered[function.__name__] = function
            return function
    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(FastMCP=FakeFastMCP))
    service, _, _, _ = kb
    server = create_server(service)
    assert set(server.registered) == {"search_passages", "get_passage", "get_item_sections", "kb_status"}
    assert server.registered["get_passage"]("../../.env")["error_code"] == "INVALID_ARGUMENT"
    assert server.registered["kb_status"]()["data"]["read_only"]


def test_real_fastmcp_in_memory_dispatch(kb):
    """End-to-end MCP tool call; runs on Windows once fastmcp is installed."""
    pytest.importorskip("fastmcp")
    import asyncio
    from fastmcp import Client

    service, _, _, _ = kb

    async def run():
        async with Client(create_server(service)) as client:
            tools = {t.name for t in await client.list_tools()}
            assert {"search_passages", "get_passage", "get_item_sections", "kb_status"} <= tools
            status = (await client.call_tool("kb_status", {})).data
            assert status["ok"] and status["data"]["passage_count"] == 5
            hits = (await client.call_tool("search_passages", {
                "query": "cyber risk", "ticker": "MSFT", "item": "1A", "rerank": False
            })).data
            assert hits["ok"] and hits["data"]["hits"]
            ref = hits["data"]["hits"][0]["passage_id"]
            passage = (await client.call_tool("get_passage", {"passage_id": ref})).data
            assert passage["ok"] and passage["data"]["passage_id"] == ref
            rejected = (await client.call_tool("get_passage", {"passage_id": "../.env"})).data
            assert not rejected["ok"] and rejected["error_code"] == "INVALID_ARGUMENT"

    asyncio.run(run())

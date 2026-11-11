"""Stage 2C tests: no LLM, internet, or model weights needed."""
from __future__ import annotations

import json
import numpy as np
import pytest

from analyst_desk.retrieval import (
    RetrievalError, bm25_scores, build_index, build_search_records, hybrid_search,
    load_index, load_passages, recall_at_k, reciprocal_rank_fusion, rewrite_queries,
)

WORDS = ("revenue", "profit", "risk", "credit", "cash", "cyber", "income", "dividend")


class FixtureEmbeddings:
    model_name = "test-deterministic-embeddings-v1"
    def encode(self, texts):
        matrix = []
        for text in texts:
            t = text.lower()
            matrix.append([float(t.count(w)) for w in WORDS])
        return np.array(matrix, dtype=np.float32)


class FakeReranker:
    def score(self, query, texts):
        return [100.0 if "cyber" in text.lower() else 0.0 for text in texts]


def passage(pid, ticker="MSFT", item="1A", text="Risk factors include cyber security.", table=False):
    return {"passage_id": pid, "ticker": ticker, "accession": "0001-25-123",
            "report_date": "2025-12-31", "filing_date": "2026-01-15",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1/123/report.htm",
            "source_sha256": "abc123", "item": item, "is_table": table,
            "kind": "table" if table else "text", "text": text}


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "passages.jsonl"
    docs = [passage("MSFT_1", text="Cyber security risk and potential liability."),
            passage("MSFT_2", item="7", text="Operating revenue and operating income profit increased."),
            passage("GOOG_1", ticker="GOOGL", item="1A", text="Risk from competition in advertising."),
            passage("MSFT_3", item="8", text="| Account | Value |\n" + "\n".join(f"| revenue row {i} | cash {i} |" for i in range(100)), table=True)]
    path.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
    return path


def _index(corpus, tmp_path):
    folder = tmp_path / "index"
    manifest = build_index(corpus, folder, FixtureEmbeddings(), table_window_chars=180)
    return load_index(folder, corpus=corpus, expected_model=FixtureEmbeddings.model_name), manifest


def test_table_windows_retain_canonical_passage_and_provenance(corpus):
    records = build_search_records(load_passages(corpus), table_window_chars=180)
    tables = [r for r in records if r["passage_id"] == "MSFT_3"]
    assert len(tables) > 3
    assert len({r["search_id"] for r in tables}) == len(tables)
    assert all(r["text"].startswith("| Account | Value |") for r in tables)
    assert all(r["source_url"].startswith("https://www.sec.gov") for r in tables)
    assert {r["item"] for r in tables} == {"8"}


def test_index_build_load_and_provenance(corpus, tmp_path):
    idx, manifest = _index(corpus, tmp_path)
    assert manifest["passage_count"] == 4
    assert manifest["search_record_count"] > 4
    assert idx.vectors.shape[0] == len(idx.records)
    assert all(abs(np.linalg.norm(v)-1) < 0.0001 for v in idx.vectors)
    assert all("source_sha256" in r for r in idx.records)


def test_bm25_selects_exact_lexical_match(corpus, tmp_path):
    idx, _ = _index(corpus, tmp_path)
    scores = bm25_scores(idx, "cyber")
    first = int(scores.argmax())
    assert idx.records[first]["passage_id"] == "MSFT_1"


def test_hybrid_retrieval_filters_by_ticker_and_item(corpus, tmp_path):
    idx, _ = _index(corpus, tmp_path)
    hits = hybrid_search(idx, "cyber risk", FixtureEmbeddings(), ticker="MSFT", item="1A")
    assert hits and all(h["ticker"] == "MSFT" and h["item"] == "1A" for h in hits)
    assert hits[0]["passage_id"] == "MSFT_1"
    assert hybrid_search(idx, "revenue", FixtureEmbeddings(), ticker="UNKNOWN") == []


def test_reranker_moves_results_with_auditable_scores(corpus, tmp_path):
    idx, _ = _index(corpus, tmp_path)
    results = hybrid_search(idx, "risk", FixtureEmbeddings(), reranker=FakeReranker(),
                            query_rewrite=False)
    assert results[0]["passage_id"] == "MSFT_1"
    assert results[0]["rerank_score"] == 100.0


def test_table_windows_deduplicated_by_canonical_id(corpus, tmp_path):
    idx, _ = _index(corpus, tmp_path)
    results = hybrid_search(idx, "revenue cash", FixtureEmbeddings(), item="8")
    assert len(results) == 1
    assert results[0]["passage_id"] == "MSFT_3"
    assert results[0]["row_start"] is not None


def test_refuse_stale_corpus_and_wrong_embedding_model(corpus, tmp_path):
    _, _ = _index(corpus, tmp_path)
    with pytest.raises(RetrievalError, match="model mismatch"):
        load_index(tmp_path / "index", expected_model="different")
    corpus.write_text(corpus.read_text() + "\n", encoding="utf-8")
    with pytest.raises(RetrievalError, match="changed"):
        load_index(tmp_path / "index", corpus=corpus)


def test_refuse_duplicate_canonical_ids(tmp_path):
    path = tmp_path / "passages.jsonl"
    path.write_text(json.dumps(passage("A")) + "\n" + json.dumps(passage("A")))
    with pytest.raises(RetrievalError, match="Duplicate canonical"):
        load_passages(path)


def test_rewrite_and_rrf_are_deterministic():
    assert len(rewrite_queries("Compare operating margin and cybersecurity risk")) == 3
    assert len(reciprocal_rank_fusion([[1,2,2],[2,1]])) == 2
    assert reciprocal_rank_fusion([[1],[1]])[1] > reciprocal_rank_fusion([[1]])[1]
    with pytest.raises(ValueError):
        rewrite_queries("")


def test_recall_at_5_exact():
    result = [[{"passage_id": "A"}, {"passage_id":"B"}], [{"passage_id":"C"}]]
    assert recall_at_k(result, [["A", "D"], ["C"]], 5) == 0.75
    with pytest.raises(ValueError):
        recall_at_k(result, [[] , ["C"]])


def test_fails_on_corrupt_vector_metadata(corpus, tmp_path):
    _, _ = _index(corpus, tmp_path)
    file = tmp_path / "index" / "search_records.json"
    payload = json.loads(file.read_text())
    payload["manifest"]["embedding_dimension"] = 12
    file.write_text(json.dumps(payload))
    with pytest.raises(RetrievalError, match="mismatch"):
        load_index(tmp_path / "index")

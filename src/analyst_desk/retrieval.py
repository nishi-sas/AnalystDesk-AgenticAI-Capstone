"""Stage 2C: auditable offline hybrid retrieval over SEC 10-K passages.

- BM25 lexical search (implemented directly, no pickle)
- Dense vector search (SentenceTransformer embeddings, stored as NumPy arrays)
- Reciprocal Rank Fusion (RRF) and optional CrossEncoder re-ranking
- Table-aware row windows retain their canonical parent passage ID
- Every hit retains filing provenance, with no generated text or facts

The JSONL corpus is produced by analyst_desk.parse_cli (Stage 2B).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


class RetrievalError(RuntimeError):
    """Invalid or inconsistent index; never return unverified matches."""


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.casefold())


def _sha256(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_passages(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise RetrievalError(f"Passage corpus not found: {path}")
    out = []
    ids = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RetrievalError(f"Invalid passage JSONL line {line_no}") from exc
        required = ("passage_id", "text", "ticker", "accession", "report_date", "item",
                    "source_url", "source_sha256", "is_table")
        if not isinstance(doc, dict) or any(k not in doc for k in required):
            raise RetrievalError(f"Missing required provenance at passage line {line_no}")
        if doc["passage_id"] in ids:
            raise RetrievalError(f"Duplicate canonical passage ID: {doc['passage_id']}")
        if not isinstance(doc["text"], str) or not doc["text"].strip():
            raise RetrievalError(f"Empty text in {doc['passage_id']}")
        if doc["item"] not in ("1A", "7", "8"):
            raise RetrievalError(f"Unexpected SEC item in {doc['passage_id']}")
        ids.add(doc["passage_id"])
        out.append(doc)
    if not out:
        raise RetrievalError("Empty passage corpus")
    return out


def _window_table(text: str, max_chars: int = 1600) -> list[tuple[str, int, int]]:
    """Index table in row groups while retaining the entire original table elsewhere."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(text) <= max_chars or len(lines) <= 2:
        return [(text, 0, max(0, len(lines) - 1))]
    # Repeat one header row in each child for column interpretation.
    header = lines[0]
    output: list[tuple[str, int, int]] = []
    current: list[str] = []
    start = 1
    def emit():
        nonlocal current, start
        if current:
            end = start + len(current) - 1
            output.append(("\n".join([header] + current), start, end))
            start = end + 1
            current = []
    for line in lines[1:]:
        if current and len(header) + sum(len(s) + 1 for s in current) + len(line) + 2 > max_chars:
            emit()
        # A giant row might exceed max_chars; preserve it in its own window instead of truncating.
        current.append(line)
    emit()
    return output


def build_search_records(passages: Sequence[dict], *, table_window_chars: int = 1600) -> list[dict]:
    records = []
    for passage in passages:
        windows = (_window_table(passage["text"], table_window_chars)
                   if passage["is_table"] else [(passage["text"], None, None)])
        for idx, (text, row_start, row_end) in enumerate(windows):
            records.append({
                "search_id": f"{passage['passage_id']}#w{idx:04d}",
                "passage_id": passage["passage_id"],
                "ticker": passage["ticker"],
                "accession": passage["accession"],
                "report_date": passage["report_date"],
                "item": passage["item"],
                "source_url": passage["source_url"],
                "source_sha256": passage["source_sha256"],
                "is_table": passage["is_table"],
                "row_start": row_start,
                "row_end": row_end,
                "text": text,
            })
    if len({r['search_id'] for r in records}) != len(records):
        raise RetrievalError("Duplicate child search IDs")
    return records


class Embedder(Protocol):
    model_name: str
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class SentenceEmbedder:
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        result = self._model.encode(list(texts), show_progress_bar=len(texts) > 50,
                                    normalize_embeddings=True, convert_to_numpy=True,
                                    batch_size=16)
        return np.asarray(result, dtype=np.float32)


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_RERANKER_MODEL):
        from sentence_transformers import CrossEncoder
        self.model_name = model_name
        self._model = CrossEncoder(model_name, device="cpu")

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        output = self._model.predict([(query, text) for text in texts],
                                     batch_size=8, show_progress_bar=False)
        return [float(x) for x in output]


def _unit_vectors(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] == 0 or vectors.shape[1] == 0:
        raise RetrievalError("Embedding output must be a nonempty 2-D matrix")
    if not np.isfinite(vectors).all():
        raise RetrievalError("Embeddings contain NaN or infinity")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms <= 1e-8).any():
        raise RetrievalError("Embedding contains zero vector")
    return vectors / norms


def build_index(corpus: str | Path, index_dir: str | Path, embedder: Embedder,
                *, table_window_chars: int = 1600) -> dict:
    """Materialize reproducible local search index; no network after models are cached."""
    if not getattr(embedder, "model_name", ""):
        raise RetrievalError("Embedder must expose stable model_name")
    passages = load_passages(corpus)
    records = build_search_records(passages, table_window_chars=table_window_chars)
    embeddings = _unit_vectors(embedder.encode([r["text"] for r in records]))
    if embeddings.shape[0] != len(records):
        raise RetrievalError("Embedding count does not match search record count")
    path = Path(index_dir)
    path.mkdir(parents=True, exist_ok=True)
    manifest = {"format_version": 1, "embedding_model": embedder.model_name,
                "corpus_sha256": _sha256(corpus), "passage_count": len(passages),
                "search_record_count": len(records), "embedding_dimension": int(embeddings.shape[1]),
                "table_window_chars": table_window_chars}
    # Temp files, then atomic replace. Never pickle untrusted data.
    pending = path / "search_records.json.tmp"
    pending.write_text(json.dumps({"manifest": manifest, "records": records}, ensure_ascii=False),
                       encoding="utf-8")
    pending.replace(path / "search_records.json")
    pending_npz = path / "embeddings.tmp.npz"
    np.savez_compressed(pending_npz, vectors=embeddings)
    pending_npz.replace(path / "embeddings.npz")
    return manifest


@dataclass
class Index:
    records: list[dict]
    vectors: np.ndarray
    manifest: dict
    tokens_by_doc: list[list[str]]
    term_frequencies: list[Counter]
    document_frequencies: Counter
    avg_length: float


def load_index(index_dir: str | Path, *, corpus: str | Path | None = None,
               expected_model: str | None = None) -> Index:
    path = Path(index_dir)
    with (path / "search_records.json").open("r", encoding="utf-8") as fh:
        obj = json.load(fh)
    manifest, records = obj["manifest"], obj["records"]
    if manifest.get("format_version") != 1:
        raise RetrievalError("Unsupported index format")
    if corpus is not None and _sha256(corpus) != manifest["corpus_sha256"]:
        raise RetrievalError("Passage corpus has changed; rebuild index")
    if expected_model is not None and expected_model != manifest["embedding_model"]:
        raise RetrievalError("Index embedding model mismatch; rebuild index")
    with np.load(path / "embeddings.npz", allow_pickle=False) as fh:
        vectors = _unit_vectors(fh["vectors"])
    if len(records) != vectors.shape[0] or vectors.shape[1] != manifest["embedding_dimension"]:
        raise RetrievalError("Index record/embedding mismatch")
    ids = [r.get("search_id") for r in records]
    if len(ids) != len(set(ids)):
        raise RetrievalError("Duplicate search IDs in index")
    toks = [tokens(r["text"]) for r in records]
    df: Counter = Counter()
    tf = [Counter(t) for t in toks]
    for ts in toks:
        df.update(set(ts))
    return Index(records, vectors, manifest, toks, tf, df,
                 sum(len(t) for t in toks) / max(1, len(toks)))


def bm25_scores(index: Index, query: str, *, k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    """Classical Okapi BM25 with nonnegative IDF and length normalisation."""
    q = set(tokens(query))
    count = len(index.records)
    scores = np.zeros(count, dtype=np.float32)
    if not q:
        return scores
    for term in q:
        df = index.document_frequencies.get(term, 0)
        if df == 0:
            continue
        idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
        for i, tf in enumerate(index.term_frequencies):
            freq = tf.get(term, 0)
            if not freq:
                continue
            doc_len = len(index.tokens_by_doc[i])
            denom = freq + k1 * (1 - b + b * doc_len / max(index.avg_length, 1))
            scores[i] += idf * freq * (k1 + 1) / denom
    return scores


QUERY_EXPANSIONS = (
    (re.compile(r"\b(operating margin|profitability|operating income)\b", re.I),
     "revenue operating income operating margin management discussion results of operations"),
    (re.compile(r"\b(risk|risks|risk factors|regulatory|cybersecurity)\b", re.I),
     "Item 1A risk factors uncertainty cybersecurity regulation competition"),
    (re.compile(r"\b(cash flow|liquidity|capital allocation)\b", re.I),
     "Item 7 cash flows liquidity financing investing operating activities"),
)


def rewrite_queries(query: str) -> list[str]:
    """Transparent query-side rewriting; no opaque LLM hallucination."""
    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty")
    variants = [query]
    for pattern, expansion in QUERY_EXPANSIONS:
        if pattern.search(query):
            variants.append(query + " " + expansion)
    return list(dict.fromkeys(variants))[:4]


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], *, k: int = 60) -> dict[int, float]:
    if k <= 0:
        raise ValueError("RRF constant must be positive")
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(dict.fromkeys(ranking), start=1):
            fused[idx] = fused.get(idx, 0.) + 1.0 / (k + rank)
    return fused


def hybrid_search(index: Index, query: str, embedder: Embedder, *, ticker: str | None = None,
                  item: str | None = None, report_date: str | None = None,
                  top_n: int = 5, candidate_k: int = 30,
                  reranker: Any | None = None, query_rewrite: bool = True) -> list[dict]:
    if top_n < 1 or candidate_k < top_n:
        raise ValueError("Need 1 <= top_n <= candidate_k")
    if embedder.model_name != index.manifest["embedding_model"]:
        raise RetrievalError("Embedding model must match index model")
    allowed = [i for i, doc in enumerate(index.records)
               if (ticker is None or doc["ticker"].upper() == ticker.upper())
               and (item is None or doc["item"].upper() == item.upper())
               and (report_date is None or doc["report_date"] == report_date)]
    if not allowed:
        return []
    queries = rewrite_queries(query) if query_rewrite else [query.strip()]
    if not queries[0]:
        raise ValueError("Query cannot be empty")
    vectors = _unit_vectors(embedder.encode(queries))
    if vectors.shape[1] != index.vectors.shape[1]:
        raise RetrievalError("Query embedding dimension differs from index")
    rankings: list[list[int]] = []
    for q, v in zip(queries, vectors):
        lexical = bm25_scores(index, q)
        dense = index.vectors @ v
        # Lexical branch should not elevate documents that share no query tokens.
        lex = sorted((i for i in allowed if lexical[i] > 0),
                     key=lambda i: (-lexical[i], index.records[i]["search_id"]))[:candidate_k]
        vec = sorted(allowed, key=lambda i: (-dense[i], index.records[i]["search_id"]))[:candidate_k]
        rankings.extend((lex, vec))
    fused = reciprocal_rank_fusion(rankings)
    chosen = sorted(fused, key=lambda i: (-fused[i], index.records[i]["search_id"]))
    # Rerank a healthy candidate pool, and deduplicate child windows by canonical passage.
    chosen = chosen[:max(candidate_k, top_n)]
    if reranker is not None and chosen:
        scores = reranker.score(query, [index.records[i]["text"] for i in chosen])
        if len(scores) != len(chosen) or not all(math.isfinite(float(x)) for x in scores):
            raise RetrievalError("Invalid cross-encoder reranking output")
        rank_scores = dict(zip(chosen, map(float, scores)))
        chosen.sort(key=lambda i: (-rank_scores[i], -fused[i], index.records[i]["search_id"]))
    output = []
    seen_parents = set()
    for i in chosen:
        record = index.records[i]
        if record["passage_id"] in seen_parents:
            continue
        seen_parents.add(record["passage_id"])
        output.append({**record, "rrf_score": fused[i],
                       "rerank_score": rank_scores[i] if reranker is not None else None})
        if len(output) == top_n:
            break
    return output


def recall_at_k(results: Sequence[Sequence[dict]], gold: Sequence[Sequence[str]], k: int = 5) -> float:
    """Macro recall of expected canonical passage IDs, case by case."""
    if len(results) != len(gold) or not results or k <= 0:
        raise ValueError("Need aligned nonempty results and gold with k > 0")
    totals = []
    for hits, expected in zip(results, gold):
        expected_set = set(expected)
        if not expected_set:
            raise ValueError("Each gold case must have at least one expected passage")
        matched = {h["passage_id"] for h in hits[:k]} & expected_set
        totals.append(len(matched) / len(expected_set))
    return sum(totals) / len(totals)

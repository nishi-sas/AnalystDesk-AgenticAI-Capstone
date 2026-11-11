"""Build and query an offline hybrid retrieval index from Stage 2B JSONL."""
from __future__ import annotations

import argparse
import json
import sys

from analyst_desk.retrieval import (
    DEFAULT_EMBEDDING_MODEL, DEFAULT_RERANKER_MODEL, CrossEncoderReranker,
    RetrievalError, SentenceEmbedder, build_index, hybrid_search, load_index,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 2C SEC hybrid retrieval")
    actions = parser.add_subparsers(dest="action", required=True)
    b = actions.add_parser("build")
    b.add_argument("--corpus", default="data/parsed/10k_passages.jsonl")
    b.add_argument("--index", default="data/retrieval_index")
    b.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    q = actions.add_parser("query")
    q.add_argument("--corpus", default="data/parsed/10k_passages.jsonl")
    q.add_argument("--index", default="data/retrieval_index")
    q.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    q.add_argument("--query", required=True)
    q.add_argument("--ticker", default=None)
    q.add_argument("--item", default=None)
    q.add_argument("--top-n", type=int, default=5)
    q.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args(argv)
    try:
        embedder = SentenceEmbedder(args.model)
        if args.action == "build":
            result = build_index(args.corpus, args.index, embedder)
            print(json.dumps(result, indent=2))
            return 0
        index = load_index(args.index, corpus=args.corpus, expected_model=args.model)
        reranker = None if args.no_rerank else CrossEncoderReranker(DEFAULT_RERANKER_MODEL)
        hits = hybrid_search(index, args.query, embedder, ticker=args.ticker,
                             item=args.item, top_n=args.top_n, reranker=reranker)
        for n, hit in enumerate(hits, 1):
            print(f"{n}. {hit['passage_id']} | SEC Item {hit['item']} | "
                  f"{hit['ticker']} {hit['report_date']} | RRF={hit['rrf_score']:.5f}")
            print(f"   {hit['source_url']}")
            print("   " + hit["text"].replace("\n", " ")[:280])
        if not hits:
            print("NO MATCHES")
        return 0
    except (RetrievalError, OSError, ValueError, ImportError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

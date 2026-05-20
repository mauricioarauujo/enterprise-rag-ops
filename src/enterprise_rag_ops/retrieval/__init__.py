"""Hybrid retrieval over the ingested corpus.

Phase 2 indexes `data/processed/corpus.jsonl` (the `Document` contract from
`ingest`) into a BM25 lexical index, a dense embedding matrix, and a LanceDB
vector store, then serves queries through `HybridRetriever`.
"""

"""LanceDB-backed dense vector store (FR-5, FR-7).

All LanceDB-specific code (connection, schema, pre-filter syntax) lives behind
the `VectorStore` Protocol so the anticipated LanceDB→Qdrant swap recorded in
ADR-002 is a new file implementing the same Protocol — not a rewrite (NFR-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa

from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.schema import Chunk


class LanceDBStore:
    """A LanceDB table with `chunk_id`, `doc_id`, `source_type`, `text`, `vector`.

    `source_type` is a regular column and is queried as a SQL-style pre-filter
    via `LanceQueryBuilder.where(..., prefilter=True)` — that pushes the filter
    *before* the ANN search rather than re-ranking results after, which matches
    the FR-7 contract.
    """

    def __init__(self, path: Path, table_name: str = config.LANCEDB_TABLE) -> None:
        self._path = path
        self._table_name = table_name
        self._db = lancedb.connect(str(path))
        # `list_tables()` returns a paginated response object; the table names
        # live on `.tables`. The old `table_names()` is deprecated.
        existing = self._db.list_tables().tables
        self._table = self._db.open_table(table_name) if table_name in existing else None

    @classmethod
    def open(cls, path: Path, table_name: str = config.LANCEDB_TABLE) -> LanceDBStore:
        """Open an existing store (assumes `path` already contains the table)."""
        return cls(path=path, table_name=table_name)

    @staticmethod
    def _schema(dim: int) -> pa.Schema:
        return pa.schema(
            [
                pa.field("chunk_id", pa.string()),
                pa.field("doc_id", pa.string()),
                pa.field("source_type", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), dim)),
            ]
        )

    def add(
        self,
        chunks: Sequence[Chunk],
        vectors: np.ndarray,
        source_types: Sequence[str],
    ) -> None:
        """Create-or-replace the table from a parallel chunk / vector / source_type triple.

        We always create-and-overwrite: the build pipeline is the only writer
        and its idempotency lives at the pipeline layer (FR-10), not here.
        """
        if not (len(chunks) == vectors.shape[0] == len(source_types)):
            raise ValueError(
                f"length mismatch: chunks={len(chunks)} vectors={vectors.shape[0]} "
                f"source_types={len(source_types)}"
            )
        dim = int(vectors.shape[1])
        rows = [
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "source_type": source_type,
                "text": chunk.text,
                "vector": vector.tolist(),
            }
            for chunk, vector, source_type in zip(chunks, vectors, source_types, strict=True)
        ]
        self._table = self._db.create_table(
            self._table_name,
            data=rows,
            schema=self._schema(dim),
            mode="overwrite",
        )

    def dense_search(
        self,
        query_vector: np.ndarray,
        k: int,
        source_type_filter: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return `(chunk_id, cosine_similarity)` pairs, best first.

        LanceDB returns `_distance` for cosine = 1 - cosine_similarity; we
        convert back so callers (abstention gate, RRF tie-break) see a real
        similarity in [-1, 1].
        """
        if self._table is None:
            raise RuntimeError(
                f"LanceDB table {self._table_name!r} not initialized — call add() first"
            )
        query = self._table.search(
            query_vector.astype(np.float32, copy=False), vector_column_name="vector"
        )
        # LanceDB's default distance for an unindexed table is L2; force cosine.
        query = query.metric("cosine")
        if source_type_filter is not None:
            # SQL-escape single quotes — defensive, even though Phase 2 callers
            # are internal (NON-BLOCKING #3 in REVIEW.md). Sprint 3 should
            # replace this with a parameterised LanceDB filter once exposed via API.
            safe = source_type_filter.replace("'", "''")
            query = query.where(f"source_type = '{safe}'", prefilter=True)
        records = query.limit(k).to_list()
        return [(r["chunk_id"], 1.0 - float(r["_distance"])) for r in records]

    def fetch_chunks_by_chunk_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        """LanceDB read filtered by `chunk_id IN (...)` (FR-5).

        Returns the requested chunks — no ordering guarantee. The
        `ContextAssembler` restores rank order from the ranked `chunk_id` list it
        already holds. SQL-style filter mirrors `dense_search`'s `source_type`
        pre-filter idiom; single-quote escaping is the same defensive pattern.
        """
        if self._table is None:
            raise RuntimeError(
                f"LanceDB table {self._table_name!r} not initialized — call add() first"
            )
        if not chunk_ids:
            return []
        quoted = ", ".join(f"'{c.replace(chr(39), chr(39) * 2)}'" for c in chunk_ids)
        where_clause = f"chunk_id IN ({quoted})"
        records = (
            self._table.search().where(where_clause, prefilter=True).limit(len(chunk_ids)).to_list()
        )
        return [Chunk(chunk_id=r["chunk_id"], doc_id=r["doc_id"], text=r["text"]) for r in records]

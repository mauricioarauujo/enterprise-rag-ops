"""Tests for deterministic JSONL serialization."""

import json

from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.ingest.writer import read_corpus, write_corpus


def _docs() -> list[Document]:
    return [
        Document(id="d2", source_type="slack", text="second", metadata={"title": "B"}),
        Document(id="d1", source_type="jira", text="first", metadata={"title": "A"}),
    ]


def test_write_corpus_returns_count_and_writes_lines(tmp_path):
    path = tmp_path / "corpus.jsonl"
    count = write_corpus(_docs(), path)
    assert count == 2
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_write_corpus_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "deeper" / "corpus.jsonl"
    write_corpus(_docs(), path)
    assert path.exists()


def test_round_trip_preserves_documents(tmp_path):
    path = tmp_path / "corpus.jsonl"
    write_corpus(_docs(), path)
    loaded = list(read_corpus(path))
    assert loaded == _docs()


def test_output_keys_are_sorted(tmp_path):
    path = tmp_path / "corpus.jsonl"
    write_corpus(_docs(), path)
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    keys = list(json.loads(first_line).keys())
    assert keys == sorted(keys)


def test_two_writes_are_byte_identical(tmp_path):
    # NFR-1 / AC-4: same input must serialize to a byte-identical file.
    path_a = tmp_path / "a.jsonl"
    path_b = tmp_path / "b.jsonl"
    write_corpus(_docs(), path_a)
    write_corpus(_docs(), path_b)
    assert path_a.read_bytes() == path_b.read_bytes()

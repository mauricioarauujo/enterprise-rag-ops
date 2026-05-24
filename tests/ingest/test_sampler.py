"""Tests for deterministic stratified sampling."""

import pytest

from enterprise_rag_ops.ingest.sampler import gold_aware_sample, stratified_sample
from enterprise_rag_ops.ingest.schema import Document


def _doc(doc_id: str, source_type: str) -> Document:
    return Document(id=doc_id, source_type=source_type, text="body")


def test_takes_first_n_per_source_by_sorted_id():
    docs = [_doc(f"{src}-{i:02d}", src) for src in ("a", "b") for i in (3, 1, 2, 0)]
    sample = stratified_sample(docs, docs_per_source=2)
    assert [d.id for d in sample] == ["a-00", "a-01", "b-00", "b-01"]


def test_result_ordered_by_source_then_id():
    docs = [_doc("z-1", "z"), _doc("a-2", "a"), _doc("a-1", "a"), _doc("z-0", "z")]
    sample = stratified_sample(docs, docs_per_source=5)
    assert [d.id for d in sample] == ["a-1", "a-2", "z-0", "z-1"]


def test_source_with_fewer_than_n_docs_keeps_all():
    docs = [_doc("a-1", "a"), _doc("b-1", "b"), _doc("b-2", "b")]
    sample = stratified_sample(docs, docs_per_source=10)
    assert sorted(d.id for d in sample) == ["a-1", "b-1", "b-2"]


def test_deterministic_across_runs():
    docs = [_doc(f"s-{i:03d}", "s") for i in range(50)]
    first = [d.id for d in stratified_sample(docs, docs_per_source=7)]
    second = [d.id for d in stratified_sample(reversed(docs), docs_per_source=7)]
    assert first == second


def test_trim_path_preserves_correct_first_n():
    # Far more than 2 * docs_per_source docs per source forces the in-stream trim.
    docs = [_doc(f"s-{i:04d}", "s") for i in range(1000)]
    sample = stratified_sample(reversed(docs), docs_per_source=5)
    assert [d.id for d in sample] == [f"s-{i:04d}" for i in range(5)]


def test_docs_per_source_below_one_raises():
    with pytest.raises(ValueError, match="docs_per_source"):
        stratified_sample([], docs_per_source=0)


def test_gold_aware_sample_includes_all_gold_docs():
    # Gold docs must be present, ordered by id first, then distractors per source
    docs = [
        _doc("a-gold", "a"),
        _doc("a-1", "a"),
        _doc("a-2", "a"),
        _doc("b-gold", "b"),
        _doc("b-1", "b"),
    ]
    gold_ids = {"a-gold", "b-gold"}
    sample = gold_aware_sample(docs, gold_ids, distractors_per_source=1)

    # Gold docs are sorted by id: a-gold, b-gold
    # Distractors per source: 1 for a (a-1 since a-1 < a-2), 1 for b (b-1)
    # Expected order: gold docs sorted, then distractors sorted by source then id
    assert [d.id for d in sample] == ["a-gold", "b-gold", "a-1", "b-1"]


def test_gold_aware_sample_excludes_gold_from_distractors():
    docs = [
        _doc("a-gold", "a"),
        _doc("a-1", "a"),
        _doc("a-2", "a"),
    ]
    gold_ids = {"a-gold"}
    # distractors_per_source = 1 should get "a-1" (since "a-gold" is excluded from distractors)
    sample = gold_aware_sample(docs, gold_ids, distractors_per_source=1)
    assert [d.id for d in sample] == ["a-gold", "a-1"]


def test_gold_aware_sample_with_empty_gold_set():
    docs = [
        _doc("a-2", "a"),
        _doc("a-1", "a"),
        _doc("b-1", "b"),
    ]
    # empty gold set behaves like stratified_sample
    sample = gold_aware_sample(docs, set(), distractors_per_source=1)
    assert [d.id for d in sample] == ["a-1", "b-1"]


def test_gold_aware_sample_determinism():
    docs = [_doc(f"s-{i:03d}", "s") for i in range(50)]
    gold_ids = {"s-010", "s-020"}
    first = [d.id for d in gold_aware_sample(docs, gold_ids, distractors_per_source=5)]
    second = [d.id for d in gold_aware_sample(reversed(docs), gold_ids, distractors_per_source=5)]
    assert first == second


def test_gold_aware_sample_below_one_raises():
    with pytest.raises(ValueError, match="distractors_per_source"):
        gold_aware_sample([], set(), distractors_per_source=0)

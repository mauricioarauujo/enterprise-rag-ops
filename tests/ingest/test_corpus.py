"""Offline corpus smoke test (FR-7).

`make check-data` runs the `corpus`-marked test here against the real
`data/processed/corpus.jsonl`. The unmarked fixture tests exercise the same
validation logic and run as part of `make test`. No test in this file touches
the network (NFR-3).
"""

import json
import os
from pathlib import Path

import pytest

from enterprise_rag_ops.ingest import config

FIXTURES = Path(__file__).parent / "fixtures"
CORRUPT_FIXTURES = sorted(FIXTURES.glob("corpus_corrupt_*.jsonl"))


def validate_corpus(path: Path, docs_per_source: int) -> list[str]:
    """Check a JSONL corpus for integrity; return human-readable errors.

    An empty list means the corpus is valid. Checks: file exists, parses as
    JSON, every source type is represented, no document has empty text, all ids
    are unique, and no source exceeds `docs_per_source`.
    """
    if not path.exists():
        return [f"corpus file missing: {path}"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    counts: dict[str, int] = {}

    with path.open(encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {lineno}: invalid JSON ({exc})")
                continue

            doc_id = record.get("id")
            if not (record.get("text") or "").strip():
                errors.append(f"line {lineno}: empty text (id={doc_id})")
            if doc_id in seen_ids:
                errors.append(f"line {lineno}: duplicate id {doc_id!r}")
            seen_ids.add(doc_id)
            counts[record.get("source_type")] = counts.get(record.get("source_type"), 0) + 1

    if not counts:
        errors.append("corpus is empty")

    missing = set(config.SOURCE_TYPES) - counts.keys()
    if missing:
        errors.append(f"missing source types: {sorted(missing)}")

    for source_type, count in sorted(counts.items()):
        if not 1 <= count <= docs_per_source:
            errors.append(
                f"source {source_type!r}: {count} documents outside expected "
                f"range 1..{docs_per_source}"
            )
    return errors


def test_valid_fixture_has_no_errors():
    assert validate_corpus(FIXTURES / "corpus_valid.jsonl", docs_per_source=100) == []


def test_missing_file_is_reported(tmp_path):
    errors = validate_corpus(tmp_path / "absent.jsonl", docs_per_source=100)
    assert errors and "missing" in errors[0]


@pytest.mark.parametrize("fixture", CORRUPT_FIXTURES, ids=lambda p: p.stem)
def test_corrupt_fixture_is_detected(fixture):
    assert validate_corpus(fixture, docs_per_source=100), f"{fixture.name} should fail"


@pytest.mark.corpus
def test_live_corpus_is_valid():
    """Validate the real corpus produced by `make download-data`.

    Fails (does not skip) when the corpus is absent, so `make check-data` is a
    genuine gate. `DOCS_PER_SOURCE` mirrors the Makefile variable.
    """
    docs_per_source = int(os.environ.get("DOCS_PER_SOURCE", config.DEFAULT_DOCS_PER_SOURCE))
    errors = validate_corpus(config.CORPUS_PATH, docs_per_source)
    assert not errors, "corpus validation failed:\n" + "\n".join(errors)

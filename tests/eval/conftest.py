"""Shared fixtures for eval tests.

Mirrors `tests/generation/conftest.py`: an offline fake OpenAI client (for
`OpenAIJudge` call-shape / prompt assertions) plus hand-built sample inputs. No network,
no API key, no model download — the whole eval test surface runs under `make test`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from enterprise_rag_ops.eval.schema import _LLMJudgeVerdict
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


class FakeOpenAIClient:
    """`OpenAI`-shaped fake — only `chat.completions.create` is exercised.

    Records every `create` call's kwargs in `self.calls` and returns a canned
    structured-output payload, so tests can assert exactly-one call, the `strict`
    json_schema sent, and the rendered prompt — with no network.
    """

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def canned_verdict_payload() -> str:
    """A valid `_LLMJudgeVerdict` JSON payload the fake client returns by default.

    Two facts (present, absent) and two citations (supported, unsupported) — a mixed
    verdict set so aggregation yields non-trivial, < 1.0 ratios.
    """
    verdict = _LLMJudgeVerdict.model_validate(
        {
            "per_fact": [
                {"fact": "Paris is the capital of France.", "verdict": "present"},
                {"fact": "France is in Europe.", "verdict": "absent"},
            ],
            "per_citation": [
                {"doc_id": "doc_real", "verdict": "supported"},
                {"doc_id": "gd_unrelated", "verdict": "unsupported"},
            ],
        }
    )
    return verdict.model_dump_json()


@pytest.fixture
def sample_answer() -> AnswerWithSources:
    """An answer citing one real doc and one spurious (unrelated) doc — the anchor case."""
    return AnswerWithSources(
        answer="The capital of France is Paris.",
        sources=["doc_real", "gd_unrelated"],
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Retrieved docs: `doc_real` supports the claim; `gd_unrelated` does not."""
    return [
        Chunk(
            chunk_id="doc_real::0",
            doc_id="doc_real",
            text="Paris is the capital and most populous city of France.",
        ),
        Chunk(
            chunk_id="gd_unrelated::0",
            doc_id="gd_unrelated",
            text="Q3 marketing offsite agenda: budget review and team lunch logistics.",
        ),
    ]


@pytest.fixture
def sample_facts() -> list[str]:
    return ["Paris is the capital of France.", "France is in Europe."]


@pytest.fixture
def vcr_record():
    """Configure VCR with record mode based on environment variable or default to none."""
    import os

    import vcr

    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    return vcr.VCR(
        cassette_library_dir="tests/eval/cassettes",
        record_mode=record_mode,
        filter_headers=["authorization"],
    )

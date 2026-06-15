"""`Judge` seam contract tests (AC-5/8/10).

Offline by construction — `StubJudge` needs no API key and no network, so this module
runs under `make test`. `OpenAIJudge` is checked for structural conformance to the
`Judge` Protocol without being instantiated (instantiation would require a key).

Corpus-coverage caveat (AC-13 / Q4): the dev subset contains gold docs for only ~3 of
the benchmark's 500 questions. Low end-to-end recall under that corpus is a
**data-coverage artifact, not a judge failure** — the judge scores generated text
against supplied facts/citations, not retrieval quality. The real fix (gold-aware corpus
sampling) is a Phase 5 task; no `corpus_coverage_warning` field is implemented here.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.interfaces import Judge
from enterprise_rag_ops.eval.openai_judge import OpenAIJudge
from enterprise_rag_ops.eval.schema import JudgeVerdict
from enterprise_rag_ops.eval.stub_judge import StubJudge
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


def test_stub_judge_conforms_to_protocol():
    assert isinstance(StubJudge(), Judge)


def test_openai_judge_conforms_to_protocol():
    """Structural conformance without instantiation (no API key needed)."""
    assert issubclass(OpenAIJudge, Judge)


def test_stub_judge_returns_all_present_all_supported(sample_answer, sample_chunks, sample_facts):
    verdict = StubJudge().judge(
        question="What is the capital of France?",
        answer_with_sources=sample_answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )
    assert isinstance(verdict, JudgeVerdict)
    assert [f.verdict for f in verdict.per_fact] == ["present", "present"]
    assert [c.verdict for c in verdict.per_citation] == ["supported", "supported"]
    # Aggregates computed via the real aggregate() — all present / all supported → 1.0.
    assert verdict.fact_recall == 1.0
    assert verdict.fact_precision == 1.0
    assert verdict.faithfulness_ratio == 1.0


def test_stub_judge_emits_none_supporting_doc_id(sample_answer, sample_chunks, sample_facts):
    """AC-6: StubJudge emits supporting_doc_id is None on every per_fact entry."""
    verdict = StubJudge().judge(
        question="What is the capital of France?",
        answer_with_sources=sample_answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )
    assert verdict.per_fact  # non-empty, so the assertion below is meaningful
    assert all(f.supporting_doc_id is None for f in verdict.per_fact)


def test_stub_judge_preserves_fact_and_citation_order(sample_chunks):
    answer = AnswerWithSources(answer="a", sources=["d2", "d1"])
    verdict = StubJudge().judge(
        question="q",
        answer_with_sources=answer,
        answer_facts=["fact one", "fact two", "fact three"],
        retrieved_docs=sample_chunks,
    )
    assert [f.fact for f in verdict.per_fact] == ["fact one", "fact two", "fact three"]
    assert [c.doc_id for c in verdict.per_citation] == ["d2", "d1"]


def test_stub_judge_abstention_no_facts_no_citations():
    """Empty facts + empty sources → (None, None, None), the N/A abstention case."""
    verdict = StubJudge().judge(
        question="q",
        answer_with_sources=AnswerWithSources(answer="I don't know.", sources=[]),
        answer_facts=[],
        retrieved_docs=[Chunk(chunk_id="x::0", doc_id="x", text="t")],
    )
    assert verdict.per_fact == []
    assert verdict.per_citation == []
    assert verdict.fact_recall is None
    assert verdict.fact_precision is None
    assert verdict.faithfulness_ratio is None

"""Anchor case: the spurious-citation thesis (FR-10, AC-11).

The motivating failure the judge must catch — an answer that cites a `doc_id` whose text
does **not** support the claim ("the capital of France is Paris" cited against an
unrelated google_drive doc). Two offline proofs:

1. A hand-built verdict through `aggregate` — non-circular: shows an `unsupported`
   citation in a mixed set drags `faithfulness_ratio` below 1.0.
2. The `OpenAIJudge` path with a fake client — shows the prompt renders the unrelated doc
   in its own named block (the per-`doc_id` isolation that *enables* the judge to mark it
   `unsupported`), and that the returned verdict carries that `unsupported` citation.

Neither hits the network.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.aggregate import aggregate
from enterprise_rag_ops.eval.openai_judge import OpenAIJudge
from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict
from tests.eval.conftest import FakeOpenAIClient


def test_handbuilt_unsupported_citation_drags_faithfulness_below_one():
    per_fact = [FactVerdict(fact="Paris is the capital of France.", verdict="present")]
    per_citation = [
        CitationVerdict(doc_id="doc_real", verdict="supported"),
        CitationVerdict(doc_id="gd_unrelated", verdict="unsupported"),
    ]
    _, _, faithfulness = aggregate(per_fact, per_citation)
    assert faithfulness == 0.5
    assert faithfulness < 1.0
    assert any(c.verdict == "unsupported" for c in per_citation)


def test_openai_judge_anchor_path(
    canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    """The judge isolates each cited doc in its own block and surfaces the unsupported one."""
    client = FakeOpenAIClient(canned_verdict_payload)
    verdict = OpenAIJudge(client=client).judge(
        question="What is the capital of France?",
        answer_with_sources=sample_answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )

    # The unrelated doc is rendered in its own named block, separate from the real one —
    # the discriminator that lets a judge say "this doc does not support the claim".
    user_msg = client.calls[0]["messages"][1]["content"]
    assert "=== doc gd_unrelated ===" in user_msg
    assert "=== doc doc_real ===" in user_msg

    spurious = [c for c in verdict.per_citation if c.doc_id == "gd_unrelated"]
    assert spurious and spurious[0].verdict == "unsupported"
    assert verdict.faithfulness_ratio < 1.0


def test_retrieved_documents_block_is_distinct_from_cited(
    canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    """AC-3: the RETRIEVED DOCUMENTS block renders every retrieved doc_id, separate from CITED."""
    client = FakeOpenAIClient(canned_verdict_payload)
    OpenAIJudge(client=client).judge(
        question="What is the capital of France?",
        answer_with_sources=sample_answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )
    user_msg = client.calls[0]["messages"][1]["content"]

    # Two distinct section headers — the retrieved menu supplements, not replaces, cited.
    assert "CITED DOCUMENTS" in user_msg
    assert "RETRIEVED DOCUMENTS" in user_msg
    assert user_msg.index("CITED DOCUMENTS") < user_msg.index("RETRIEVED DOCUMENTS")

    # Every retrieved doc_id appears as its own block under the retrieved menu.
    retrieved_section = user_msg[user_msg.index("RETRIEVED DOCUMENTS") :]
    for chunk in sample_chunks:
        assert f"=== doc {chunk.doc_id} ===" in retrieved_section


def test_hallucination_guard_collapses_out_of_set_doc_id(
    canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    """AC-5: an emitted supporting_doc_id not in the retrieved set collapses to None;
    an in-set id is retained.

    The canned payload emits `doc_real` (in `sample_chunks`) for fact 1 and the
    not-retrieved `gd_hallucinated` for fact 2.
    """
    client = FakeOpenAIClient(canned_verdict_payload)
    verdict = OpenAIJudge(client=client).judge(
        question="What is the capital of France?",
        answer_with_sources=sample_answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )

    by_fact = {fv.fact: fv for fv in verdict.per_fact}
    # In-set id retained.
    assert by_fact["Paris is the capital of France."].supporting_doc_id == "doc_real"
    # Out-of-set id collapsed to None by the guard.
    assert by_fact["France is in Europe."].supporting_doc_id is None

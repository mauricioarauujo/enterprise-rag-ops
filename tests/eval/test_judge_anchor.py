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

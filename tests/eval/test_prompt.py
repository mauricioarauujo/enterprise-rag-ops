"""Tests for the judge-prompt builders (FR-6, NFR-2).

Direct unit coverage of `eval/prompt.py`, mirroring `tests/generation/test_prompt.py`:
the byte-identical determinism invariant, the embedded LLM-facing schema, the numbered
fact checklist, the per-`doc_id` block rendering, and the `(text unavailable)` fallback.
Pure functions — no client, no I/O, no network.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.prompt import build_judge_system_prompt, build_judge_user_prompt


def test_system_prompt_is_byte_identical_across_calls():
    """NFR-2: same inputs → byte-identical output."""
    assert build_judge_system_prompt() == build_judge_system_prompt()


def test_system_prompt_embeds_llm_facing_schema_only():
    prompt = build_judge_system_prompt()
    assert "RAG evaluation judge" in prompt
    # The two LLM-facing lists are in the embedded schema...
    assert '"per_fact"' in prompt
    assert '"per_citation"' in prompt
    assert "additionalProperties" in prompt
    # ...but the Python-derived aggregate floats never enter the LLM contract.
    assert "fact_recall" not in prompt
    assert "faithfulness_ratio" not in prompt


def test_user_prompt_renders_numbered_facts_and_per_doc_blocks():
    prompt = build_judge_user_prompt(
        question="What is the capital of France?",
        answer="The capital of France is Paris.",
        answer_facts=["Paris is the capital of France.", "France is in Europe."],
        cited_docs=[("doc_real", "Paris is the capital of France."), ("gd_x", "unrelated text")],
    )
    # 1-based numbered fact checklist.
    assert "1. Paris is the capital of France." in prompt
    assert "2. France is in Europe." in prompt
    # One separately named block per cited doc_id (not a merged blob).
    assert "=== doc doc_real ===" in prompt
    assert "=== doc gd_x ===" in prompt


def test_user_prompt_marks_unavailable_doc():
    """A cited doc with no text (not in the retrieved set) gets an explicit block."""
    prompt = build_judge_user_prompt(
        question="q",
        answer="a",
        answer_facts=["f"],
        cited_docs=[("doc_missing", None)],
    )
    assert "=== doc doc_missing (text unavailable) ===" in prompt


def test_user_prompt_is_byte_identical_across_calls():
    args = dict(question="q", answer="a", answer_facts=["f"], cited_docs=[("d", "t")])
    assert build_judge_user_prompt(**args) == build_judge_user_prompt(**args)


def test_user_prompt_empty_facts_and_docs_does_not_raise():
    """Defensive — the abstention shape (no facts, no citations) must not crash."""
    prompt = build_judge_user_prompt(question="q", answer="a", answer_facts=[], cited_docs=[])
    assert "QUESTION:" in prompt

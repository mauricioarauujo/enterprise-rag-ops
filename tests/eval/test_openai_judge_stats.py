"""Unit tests for OpenAIJudge's judge_with_stats implementation (AC-3)."""

from __future__ import annotations

from types import SimpleNamespace

from enterprise_rag_ops.eval.interfaces import Judge
from enterprise_rag_ops.eval.openai_judge import OpenAIJudge
from enterprise_rag_ops.eval.schema import _LLMJudgeVerdict
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


class FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeOpenAIClient:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        usage = FakeUsage(self.prompt_tokens, self.completion_tokens)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def test_openai_judge_judge_with_stats():
    """AC-3: OpenAIJudge.judge_with_stats times call and returns JudgeVerdict + CallStats."""
    llm_payload = _LLMJudgeVerdict.model_validate(
        {
            "per_fact": [
                {"fact": "Paris is the capital of France.", "verdict": "present"},
            ],
            "per_citation": [
                {"doc_id": "doc_1", "verdict": "supported"},
            ],
        }
    ).model_dump_json()

    fake_client = FakeOpenAIClient(llm_payload, prompt_tokens=220, completion_tokens=35)

    judge = OpenAIJudge(model="gpt-5-nano-test", client=fake_client)

    answer = AnswerWithSources(answer="Paris is the capital.", sources=["doc_1"])
    chunks = [Chunk(chunk_id="doc_1::0", doc_id="doc_1", text="Paris is the capital of France.")]

    result, stats = judge.judge_with_stats(
        question="What is the capital of France?",
        answer_with_sources=answer,
        answer_facts=["Paris is the capital of France."],
        retrieved_docs=chunks,
    )

    assert result.fact_recall == 1.0
    assert result.faithfulness_ratio == 1.0

    assert stats.input_tokens == 220
    assert stats.output_tokens == 35
    assert stats.latency_s > 0.0
    assert stats.model == "gpt-5-nano-test"
    assert stats.system == "openai"

    # Assert judge protocol is untouched
    assert issubclass(OpenAIJudge, Judge)
    protocol_methods = [m for m in dir(Judge) if not m.startswith("_")]
    assert "judge" in protocol_methods
    assert "judge_with_stats" not in protocol_methods

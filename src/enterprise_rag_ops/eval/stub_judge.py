"""CI-safe `Judge` (FR-7) — no API key, no network.

The deterministic drop-in for `OpenAIJudge` through the `Judge` seam, used to exercise
the eval wiring offline (NFR-1). Returns every supplied fact `present` and every cited
`doc_id` `supported`, and computes the three aggregates via the real `aggregate`
function — so the stub path also exercises true aggregation. Mirrors `StubGenerator`.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.aggregate import aggregate
from enterprise_rag_ops.eval.raw_call import RawCall
from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict, JudgeVerdict
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


class StubJudge:
    """Returns an all-`present` / all-`supported` `JudgeVerdict` deterministically."""

    def __init__(self, model: str | None = None, **kwargs) -> None:
        self._model = model or "stub"

    def judge(
        self,
        question: str,
        answer_with_sources: AnswerWithSources,
        answer_facts: list[str],
        retrieved_docs: list[Chunk],
    ) -> JudgeVerdict:
        per_fact = [FactVerdict(fact=fact, verdict="present") for fact in answer_facts]
        per_citation = [
            CitationVerdict(doc_id=doc_id, verdict="supported")
            for doc_id in answer_with_sources.sources
        ]
        fact_recall, fact_precision, faithfulness_ratio = aggregate(per_fact, per_citation)
        return JudgeVerdict(
            per_fact=per_fact,
            per_citation=per_citation,
            fact_recall=fact_recall,
            fact_precision=fact_precision,
            faithfulness_ratio=faithfulness_ratio,
        )

    def judge_with_stats(
        self,
        question: str,
        answer_with_sources: AnswerWithSources,
        answer_facts: list[str],
        retrieved_docs: list[Chunk],
    ) -> tuple[JudgeVerdict, CallStats, RawCall]:
        verdict = self.judge(question, answer_with_sources, answer_facts, retrieved_docs)
        stats = CallStats(
            input_tokens=0,
            output_tokens=0,
            latency_s=0.0,
            model="stub",
            system="openai",
            cost_usd=0.0,
        )
        serialized_per_fact = (
            [fv.model_dump() for fv in verdict.per_fact] if verdict.per_fact else []
        )
        serialized_per_citation = (
            [cv.model_dump() for cv in verdict.per_citation] if verdict.per_citation else []
        )
        raw_call = RawCall(
            request={
                "model": self._model,
                "messages": [{"role": "user", "content": question}],
            },
            response={
                "per_fact": serialized_per_fact,
                "per_citation": serialized_per_citation,
            },
        )
        return verdict, stats, raw_call

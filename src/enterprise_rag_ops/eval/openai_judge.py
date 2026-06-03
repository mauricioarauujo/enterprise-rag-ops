"""OpenAI-backed `Judge` using structured outputs (FR-6, NFR-2/4/7).

Issues a single `client.chat.completions.create` call with
`response_format={"type": "json_schema", "json_schema": ..., "strict": true}` built from
the **LLM-facing** schema (`_LLMJudgeVerdict` — the two verdict lists only; the aggregate
floats never enter the LLM contract). Defensively re-validates the returned JSON through
Pydantic so drift surfaces as a typed `ValidationError`, then runs the pure-Python
`aggregate` and assembles the public `JudgeVerdict`. Mirrors `OpenAIGenerator` — the only
module in the eval tree that imports `openai`, preserving the offline-CI invariant.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any

from openai import OpenAI

from enterprise_rag_ops.eval.aggregate import aggregate
from enterprise_rag_ops.eval.prompt import build_judge_system_prompt, build_judge_user_prompt
from enterprise_rag_ops.eval.raw_call import RawCall
from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.eval.schema import JudgeVerdict, _LLMJudgeVerdict
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.eval")

DEFAULT_MODEL = "gpt-5-nano-2025-08-07"


def _serialize_response(response: Any) -> dict[str, Any]:
    try:
        if isinstance(response, (int, str, float, bool, list, dict)):
            raise TypeError(f"Invalid response type: {type(response)}")

        try:
            if hasattr(response, "model_dump"):
                return response.model_dump(mode="json")
        except Exception:
            pass

        # Fallback manual extraction
        res: dict[str, Any] = {}

        # model
        model = getattr(response, "model", None)
        if model is not None:
            res["model"] = model

        # system_fingerprint
        sys_fp = getattr(response, "system_fingerprint", None)
        if sys_fp is not None:
            res["system_fingerprint"] = sys_fp

        # choices
        choices = getattr(response, "choices", None)
        if choices:
            res_choices = []
            for choice in choices:
                choice_dict = {}
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason is not None:
                    choice_dict["finish_reason"] = finish_reason

                msg = getattr(choice, "message", None)
                if msg is not None:
                    msg_dict = {}
                    content = getattr(msg, "content", None)
                    if content is not None:
                        msg_dict["content"] = content
                    refusal = getattr(msg, "refusal", None)
                    if refusal is not None:
                        msg_dict["refusal"] = refusal
                    choice_dict["message"] = msg_dict
                res_choices.append(choice_dict)
            res["choices"] = res_choices

        # usage
        usage = getattr(response, "usage", None)
        if usage is not None:
            usage_dict = {}
            for f in ["prompt_tokens", "completion_tokens", "total_tokens"]:
                val = getattr(usage, f, None)
                if val is not None:
                    usage_dict[f] = val
            if usage_dict:
                res["usage"] = usage_dict

        return res
    except Exception as e:
        return {"_serialization_error": type(e).__name__}


class OpenAIJudge:
    """`Judge` implementation calling OpenAI structured outputs (FR-6).

    Default model is `gpt-5-nano-2025-08-07`; override via env var `RAG_JUDGE_MODEL`.
    Temperature is left at the model default — GPT-5-class models reject an explicit
    temperature; reproducibility is carried by `strict: true` + the closed discrete
    verdict vocabulary, mirroring `OpenAIGenerator`. No same-family assumption is
    hard-wired (Q2): the cross-family judge is the ADR-0005 swap behind the `Judge` seam.
    """

    def __init__(self, model: str | None = None, client: OpenAI | None = None) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                # NFR-7: clean error, not an SDK stack trace.
                raise RuntimeError(
                    "OPENAI_API_KEY is not set — required for OpenAIJudge. "
                    "Set it in your shell or .env before running a live judge. "
                    "CI and `make test` use StubJudge and need no key."
                )
            # `timeout` bounds a single call so a dead socket (e.g. after the host
            # sleeps mid-sweep) fails fast and retries instead of blocking forever.
            client = OpenAI(timeout=120.0)
        self._client = client
        self._model = model or os.environ.get("RAG_JUDGE_MODEL", DEFAULT_MODEL)

    def judge(
        self,
        question: str,
        answer_with_sources: AnswerWithSources,
        answer_facts: list[str],
        retrieved_docs: list[Chunk],
    ) -> JudgeVerdict:
        """Call OpenAI once and return a validated, aggregated `JudgeVerdict`."""
        result, _, _ = self.judge_with_stats(
            question, answer_with_sources, answer_facts, retrieved_docs
        )
        return result

    def judge_with_stats(
        self,
        question: str,
        answer_with_sources: AnswerWithSources,
        answer_facts: list[str],
        retrieved_docs: list[Chunk],
    ) -> tuple[JudgeVerdict, CallStats, RawCall]:
        """Call OpenAI once and return a validated, aggregated `JudgeVerdict` along with `CallStats` and `RawCall`."""
        import time

        # Resolve each cited doc_id to its text (None if not in the retrieved set),
        # preserving citation order — the per-doc_id isolation the prompt renders.
        # A doc may be split across several chunks; join them in retrieval order so the
        # judge sees the whole doc, not just the last-seen chunk for that doc_id.
        doc_chunks: dict[str, list[str]] = defaultdict(list)
        for c in retrieved_docs:
            doc_chunks[c.doc_id].append(c.text)
        doc_text = {doc_id: "\n\n".join(texts) for doc_id, texts in doc_chunks.items()}
        cited_docs = [(doc_id, doc_text.get(doc_id)) for doc_id in answer_with_sources.sources]

        system_prompt = build_judge_system_prompt()
        user_prompt = build_judge_user_prompt(
            question=question,
            answer=answer_with_sources.answer,
            answer_facts=answer_facts,
            cited_docs=cited_docs,
        )

        # Single source of truth: the LLM-facing schema is the two-list subset only.
        json_schema = {
            "name": "JudgeVerdict",
            "schema": _LLMJudgeVerdict.model_json_schema(),
            "strict": True,
        }

        messages_sent = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response_format = {"type": "json_schema", "json_schema": json_schema}

        start_time = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages_sent,
            response_format=response_format,
        )
        latency = time.perf_counter() - start_time

        raw = response.choices[0].message.content or ""
        llm_verdict = _LLMJudgeVerdict.model_validate_json(raw)

        fact_recall, fact_precision, faithfulness_ratio = aggregate(
            llm_verdict.per_fact, llm_verdict.per_citation
        )

        # Read usage stats
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="openai",
        )

        request = {
            "model": self._model,
            "messages": messages_sent,
            "response_format": response_format,
        }
        serialized_response = _serialize_response(response)
        raw_call = RawCall(request=request, response=serialized_response)

        logger.info(
            "eval.openai_judge facts=%d citations=%d recall=%s precision=%s faithfulness=%s input_tokens=%d output_tokens=%d latency_s=%.3f",
            len(llm_verdict.per_fact),
            len(llm_verdict.per_citation),
            fact_recall,
            fact_precision,
            faithfulness_ratio,
            input_tokens,
            output_tokens,
            latency,
        )
        verdict = JudgeVerdict(
            per_fact=llm_verdict.per_fact,
            per_citation=llm_verdict.per_citation,
            fact_recall=fact_recall,
            fact_precision=fact_precision,
            faithfulness_ratio=faithfulness_ratio,
        )
        return verdict, stats, raw_call

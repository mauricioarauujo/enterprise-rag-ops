"""Google-Gemini-backed `Generator` using native JSON-schema structured output (FR-2).

Calls `client.models.generate_content` with a `GenerateContentConfig` carrying
`response_mime_type="application/json"` + `response_schema=AnswerWithSources`, so the
model returns schema-shaped JSON. Defensively re-validates through Pydantic
(`model_validate_json`) so any drift surfaces as a typed `ValidationError`, and
`extra="forbid"` is enforced our side regardless of provider enforcement.

Token accounting: Gemini 2.5 thinking tokens are billed as output but are NOT included
in `candidates_token_count`, so output = candidates + thoughts (read defensively) to
stay cost-accurate. Mirrors `anthropic_generator.py` / `openai_generator.py` structure.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from enterprise_rag_ops.eval.raw_call import RawCall
from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "gemini-2.5-flash-lite"


def _serialize_logprobs_result(lr: Any) -> Any:
    try:
        if hasattr(lr, "model_dump"):
            return lr.model_dump(mode="json")
    except Exception:
        pass

    try:
        res: dict[str, Any] = {}
        top_candidates = getattr(lr, "top_candidates", None)
        if top_candidates is not None:
            serialized_top = []
            for entry in top_candidates:
                entry_dict = {}
                token_cands = getattr(entry, "candidates", None)
                if token_cands is not None:
                    serialized_tc = []
                    for tc in token_cands:
                        tc_dict = {}
                        log_prob = getattr(tc, "log_probability", None)
                        if log_prob is not None:
                            tc_dict["log_probability"] = log_prob
                        token = getattr(tc, "token", None)
                        if token is not None:
                            tc_dict["token"] = token
                        serialized_tc.append(tc_dict)
                    entry_dict["candidates"] = serialized_tc
                serialized_top.append(entry_dict)
            res["top_candidates"] = serialized_top

        chosen_candidates = getattr(lr, "chosen_candidates", None)
        if chosen_candidates is not None:
            serialized_chosen = []
            for cc in chosen_candidates:
                cc_dict = {}
                log_prob = getattr(cc, "log_probability", None)
                if log_prob is not None:
                    cc_dict["log_probability"] = log_prob
                token = getattr(cc, "token", None)
                if token is not None:
                    cc_dict["token"] = token
                serialized_chosen.append(cc_dict)
            res["chosen_candidates"] = serialized_chosen
        return res
    except Exception:
        return None


def _compute_confidence(response: Any) -> float | None:
    try:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return None
        cand = candidates[0]

        lr = getattr(cand, "logprobs_result", None)
        if lr is not None:
            top_candidates = getattr(lr, "top_candidates", None)
            if top_candidates:
                first_token_entry = top_candidates[0]
                token_cands = getattr(first_token_entry, "candidates", None)
                if token_cands and len(token_cands) >= 2:
                    p0 = getattr(token_cands[0], "log_probability", None)
                    p1 = getattr(token_cands[1], "log_probability", None)
                    if p0 is not None and p1 is not None:
                        return float(p0) - float(p1)

        avg = getattr(cand, "avg_logprobs", None)
        if avg is not None:
            return float(avg)
        return None
    except (AttributeError, IndexError, TypeError):
        return None


def _serialize_response(response: Any) -> dict[str, Any]:
    try:
        if isinstance(response, (int, str, float, bool, list, dict)):
            raise TypeError(f"Invalid response type: {type(response)}")

        try:
            if hasattr(response, "model_dump"):
                res = response.model_dump(mode="json")
                if hasattr(response, "text") and "text" not in res:
                    import contextlib

                    with contextlib.suppress(Exception):
                        res["text"] = response.text
                return res
        except Exception:
            pass

        res: dict[str, Any] = {}

        # text
        text = getattr(response, "text", None)
        if text is not None:
            res["text"] = text

        # model_version
        model_version = getattr(response, "model_version", None)
        if model_version is not None:
            res["model_version"] = model_version

        # candidates
        candidates = getattr(response, "candidates", None)
        if candidates is not None:
            serialized_candidates = []
            for candidate in candidates:
                cand_dict = {}
                finish_reason = getattr(candidate, "finish_reason", None)
                if finish_reason is not None:
                    cand_dict["finish_reason"] = finish_reason

                content = getattr(candidate, "content", None)
                if content is not None:
                    content_dict = {}
                    role = getattr(content, "role", None)
                    if role is not None:
                        content_dict["role"] = role
                    parts = getattr(content, "parts", None)
                    if parts is not None:
                        serialized_parts = []
                        for part in parts:
                            part_dict = {}
                            part_text = getattr(part, "text", None)
                            if part_text is not None:
                                part_dict["text"] = part_text
                            serialized_parts.append(part_dict)
                        content_dict["parts"] = serialized_parts
                    cand_dict["content"] = content_dict

                avg_logprobs = getattr(candidate, "avg_logprobs", None)
                if avg_logprobs is not None:
                    cand_dict["avg_logprobs"] = avg_logprobs

                logprobs_result = getattr(candidate, "logprobs_result", None)
                if logprobs_result is not None:
                    serialized_lr = _serialize_logprobs_result(logprobs_result)
                    if serialized_lr is not None:
                        cand_dict["logprobs_result"] = serialized_lr

                serialized_candidates.append(cand_dict)
            res["candidates"] = serialized_candidates

        # usage_metadata
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            usage_dict = {}
            for f in ["prompt_token_count", "candidates_token_count", "thoughts_token_count"]:
                val = getattr(usage, f, None)
                if val is not None:
                    usage_dict[f] = val
            if usage_dict:
                res["usage_metadata"] = usage_dict

        return res
    except Exception as e:
        return {"_serialization_error": type(e).__name__}


class _GeminiResponseSchema(BaseModel):
    """Open-schema mirror of `AnswerWithSources` for Gemini's `response_schema`.

    Gemini's structured-output schema dialect rejects `additionalProperties`, which
    `AnswerWithSources` emits because of its `extra="forbid"` config (passing it directly
    yields a 400 `Unknown name "additional_properties"`). So the schema handed to the SDK
    is this open variant; the real *closed*-schema contract is still enforced our side by
    `AnswerWithSources.model_validate_json(resp.text)` (FR-3), so a Gemini response with an
    extra field still raises. Fields mirror `AnswerWithSources` exactly.
    """

    answer: str
    sources: list[str]


class GeminiGenerator:
    """`Generator` implementation using Google Gemini native JSON-schema output (FR-2).

    Default model is `gemini-2.5-flash-lite`; override via env var `RAG_GEN_MODEL_GOOGLE`.
    An explicit `model=` constructor arg wins over the env var. The client auto-reads
    `GEMINI_API_KEY` or `GOOGLE_API_KEY` (GOOGLE wins if both set); inject `client=` for
    offline tests.
    """

    def __init__(self, model: str | None = None, client: genai.Client | None = None) -> None:
        if client is None:
            if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                # Clean error, not an SDK stack trace (mirrors the Anthropic/OpenAI guard).
                raise RuntimeError(
                    "Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set — required for "
                    "GeminiGenerator. Set one in your shell or .env before running evaluation."
                )
            # Harden retries for a full sweep: the SDK default is 5 attempts, which a
            # transient `503 UNAVAILABLE` ("high demand") spike can exhaust mid-sweep.
            # Mirror the Anthropic generator (max_retries=8, timeout=120: retry 429/5xx
            # with backoff, and bound a single call so a dead socket fails fast.
            client = genai.Client(
                http_options=types.HttpOptions(
                    timeout=120_000,  # milliseconds
                    retry_options=types.HttpRetryOptions(
                        attempts=8,
                        http_status_codes=[429, 500, 502, 503, 504],
                    ),
                )
            )
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL_GOOGLE", DEFAULT_MODEL)

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Call Gemini and return a validated `AnswerWithSources`."""
        result, _, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats, RawCall]:
        """Call Gemini and return a validated `AnswerWithSources` along with `CallStats` and `RawCall`."""
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(context_chunks, question)

        start_time = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                # Open mirror — Gemini rejects the `additionalProperties` that
                # AnswerWithSources(extra="forbid") emits. Closed-schema enforcement
                # still happens our side via model_validate_json below (FR-3).
                response_schema=_GeminiResponseSchema,
                response_logprobs=True,
                logprobs=5,
                system_instruction=system_prompt,
            ),
        )
        latency = time.perf_counter() - start_time

        result = AnswerWithSources.model_validate_json(response.text)

        # Token accounting. Gemini 2.5 thinking tokens are billed as output but are NOT
        # in candidates_token_count, so output = candidates + thoughts (read defensively;
        # missing metadata → 0, never crash).
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        candidates = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
        thoughts = getattr(usage, "thoughts_token_count", 0) or 0 if usage else 0
        output_tokens = candidates + thoughts

        conf = _compute_confidence(response)

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="google",
            confidence_score=conf,
        )

        request = {
            "model": self._model,
            "contents": user_prompt,
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
        }
        serialized_response = _serialize_response(response)
        raw_call = RawCall(request=request, response=serialized_response)

        logger.info(
            "generation.google sources=%s context_doc_ids=%s input_tokens=%d output_tokens=%d latency_s=%.3f",
            result.sources,
            [c.doc_id for c in context_chunks],
            input_tokens,
            output_tokens,
            latency,
        )
        return result, stats, raw_call

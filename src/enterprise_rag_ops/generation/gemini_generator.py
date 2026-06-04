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

import json
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


# Gemini-only verbalized-confidence addendum. Appended to the shared system prompt for
# the Gemini path ONLY. The cheap model (gemini-2.5-flash-lite) exposes NO token logprobs
# (the API 400s on response_logprobs — see ADR-0011), so the escalation signal is the
# model's own self-reported confidence instead. The field is parsed off the response and
# rides CallStats.confidence_score; it is stripped before AnswerWithSources validation so
# the shared output contract (answer + sources, extra="forbid") is unchanged.
_CONFIDENCE_ADDENDUM = (
    "\n\nAlso include a numeric field `confidence` between 0.0 and 1.0 expressing how "
    "confident you are that your `answer` is fully correct and entirely grounded in the "
    "provided context. Use 1.0 only when the context unambiguously supports every claim, "
    "and low values when you are unsure or the context is thin."
)


def _parse_confidence(data: dict[str, Any]) -> float | None:
    """Extract the verbalized `confidence` from the parsed response dict (defensive).

    Returns a float clamped to [0.0, 1.0], or None if absent/non-numeric — never raises.
    """
    try:
        raw = data.get("confidence")
        if raw is None:
            return None
        val = float(raw)
        if val < 0.0:
            return 0.0
        if val > 1.0:
            return 1.0
        return val
    except (TypeError, ValueError):
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
    unexpected field still raises. `answer`/`sources` mirror `AnswerWithSources`; the extra
    `confidence` field is the Gemini-only verbalized-escalation signal (ADR-0011) and is
    stripped before `AnswerWithSources` validation.
    """

    answer: str
    sources: list[str]
    confidence: float


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
        system_prompt = build_system_prompt() + _CONFIDENCE_ADDENDUM
        user_prompt = build_user_prompt(context_chunks, question)

        start_time = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                # Open mirror — Gemini rejects the `additionalProperties` that
                # AnswerWithSources(extra="forbid") emits. Closed-schema enforcement
                # still happens our side via model_validate below (FR-3). The mirror
                # carries the extra `confidence` field; the cheap model exposes no token
                # logprobs (ADR-0011), so verbalized confidence is the escalation signal.
                response_schema=_GeminiResponseSchema,
                system_instruction=system_prompt,
            ),
        )
        latency = time.perf_counter() - start_time

        # Parse once: extract the verbalized confidence, then validate answer/sources via
        # the closed AnswerWithSources contract (confidence stripped — it never enters the
        # shared output schema). Bad/odd JSON falls back to direct validation (conf=None).
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            data = None

        if isinstance(data, dict):
            confidence_score = _parse_confidence(data)
            answer_data = {k: v for k, v in data.items() if k != "confidence"}
            result = AnswerWithSources.model_validate(answer_data)
        else:
            confidence_score = None
            result = AnswerWithSources.model_validate_json(response.text)

        # Token accounting. Gemini 2.5 thinking tokens are billed as output but are NOT
        # in candidates_token_count, so output = candidates + thoughts (read defensively;
        # missing metadata → 0, never crash).
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        candidates = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
        thoughts = getattr(usage, "thoughts_token_count", 0) or 0 if usage else 0
        output_tokens = candidates + thoughts

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="google",
            confidence_score=confidence_score,
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

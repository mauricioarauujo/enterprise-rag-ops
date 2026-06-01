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

from google import genai
from google.genai import types
from pydantic import BaseModel

from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "gemini-2.5-flash-lite"


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
            client = genai.Client()
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL_GOOGLE", DEFAULT_MODEL)

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Call Gemini and return a validated `AnswerWithSources`."""
        result, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats]:
        """Call Gemini and return a validated `AnswerWithSources` along with `CallStats`."""
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

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="google",
        )

        logger.info(
            "generation.google sources=%s context_doc_ids=%s input_tokens=%d output_tokens=%d latency_s=%.3f",
            result.sources,
            [c.doc_id for c in context_chunks],
            input_tokens,
            output_tokens,
            latency,
        )
        return result, stats

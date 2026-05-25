"""Anthropic-backed `Generator` using forced tool-use (FR-3, NFR-6).

Calls `client.messages.create` with a forced tool choice to retrieve structured JSON.
Defensively validates through Pydantic to align with the Generator protocol.
"""

from __future__ import annotations

import logging
import os
import time

from anthropic import Anthropic

from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "claude-3-5-haiku-20241022"


class AnthropicGenerator:
    """`Generator` implementation using Anthropic forced tool-use structured outputs.

    Default model is `claude-3-5-haiku-20241022`; override via env var `RAG_GEN_MODEL_ANTHROPIC`.
    """

    def __init__(self, model: str | None = None, client: Anthropic | None = None) -> None:
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — required for AnthropicGenerator. "
                    "Set it in your shell or .env before running evaluation."
                )
            client = Anthropic()
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL_ANTHROPIC", DEFAULT_MODEL)

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Call Anthropic and return a validated `AnswerWithSources`."""
        result, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats]:
        """Call Anthropic and return a validated `AnswerWithSources` along with `CallStats`."""
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(context_chunks, question)

        # Build tools list mapping schema to Anthropic input_schema
        schema = AnswerWithSources.model_json_schema()
        # Remove title if present, though not strictly required, to keep it clean.
        schema.pop("title", None)

        tools = [
            {
                "name": "emit_answer",
                "description": "Emit the structured answer with sources.",
                "input_schema": schema,
            }
        ]

        start_time = time.perf_counter()
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=tools,
            tool_choice={"type": "tool", "name": "emit_answer"},
        )
        latency = time.perf_counter() - start_time

        tool_use_block = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "emit_answer":
                tool_use_block = block
                break

        if not tool_use_block:
            raise ValueError(
                f"Anthropic API response did not contain emit_answer tool_use block. Content: {response.content}"
            )

        result = AnswerWithSources.model_validate(tool_use_block.input)

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="anthropic",
        )

        logger.info(
            "generation.anthropic sources=%s context_doc_ids=%s input_tokens=%d output_tokens=%d latency_s=%.3f",
            result.sources,
            [c.doc_id for c in context_chunks],
            input_tokens,
            output_tokens,
            latency,
        )
        return result, stats

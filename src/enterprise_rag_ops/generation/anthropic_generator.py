"""Anthropic-backed `Generator` using forced tool-use (FR-3, NFR-6).

Calls `client.messages.create` with a forced tool choice to retrieve structured JSON.
Defensively validates through Pydantic to align with the Generator protocol.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from anthropic import Anthropic

from enterprise_rag_ops.eval.raw_call import RawCall
from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _serialize_response(response: Any) -> dict[str, Any]:
    try:
        if isinstance(response, (int, str, float, bool, list, dict)):
            raise TypeError(f"Invalid response type: {type(response)}")

        try:
            if hasattr(response, "model_dump"):
                return response.model_dump(mode="json")
        except Exception:
            pass

        res: dict[str, Any] = {}

        # model
        model = getattr(response, "model", None)
        if model is not None:
            res["model"] = model

        # stop_reason
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason is not None:
            res["stop_reason"] = stop_reason

        # content
        content = getattr(response, "content", None)
        if content is not None:
            serialized_content = []
            for block in content:
                block_dict = {}
                b_type = getattr(block, "type", None)
                if b_type is not None:
                    block_dict["type"] = b_type
                b_name = getattr(block, "name", None)
                if b_name is not None:
                    block_dict["name"] = b_name
                b_input = getattr(block, "input", None)
                if b_input is not None:
                    block_dict["input"] = b_input
                b_text = getattr(block, "text", None)
                if b_text is not None:
                    block_dict["text"] = b_text
                serialized_content.append(block_dict)
            res["content"] = serialized_content

        # usage
        usage = getattr(response, "usage", None)
        if usage is not None:
            usage_dict = {}
            for f in ["input_tokens", "output_tokens"]:
                val = getattr(usage, f, None)
                if val is not None:
                    usage_dict[f] = val
            if usage_dict:
                res["usage"] = usage_dict

        return res
    except Exception as e:
        return {"_serialization_error": type(e).__name__}


class AnthropicGenerator:
    """`Generator` implementation using Anthropic forced tool-use structured outputs.

    Default model is `claude-haiku-4-5-20251001` (the current cheapest Claude tier;
    the original `claude-3-5-haiku-20241022` reached end-of-life on 2026-02-19).
    Override via env var `RAG_GEN_MODEL_ANTHROPIC`.
    """

    def __init__(self, model: str | None = None, client: Anthropic | None = None) -> None:
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — required for AnthropicGenerator. "
                    "Set it in your shell or .env before running evaluation."
                )
            # Higher retry budget than the SDK default (2): tier-1 Anthropic accounts
            # cap output tokens/min low, so a full sweep throttles; the SDK honours
            # `retry-after` with backoff, letting calls ride out per-minute windows.
            # `timeout` bounds a single call so a dead socket (e.g. after the host
            # sleeps mid-sweep) fails fast and retries instead of blocking forever.
            client = Anthropic(max_retries=8, timeout=120.0)
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL_ANTHROPIC", DEFAULT_MODEL)

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Call Anthropic and return a validated `AnswerWithSources`."""
        result, _, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats, RawCall]:
        """Call Anthropic and return a validated `AnswerWithSources` along with `CallStats` and `RawCall`."""

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

        request = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "emit_answer"},
        }
        serialized_response = _serialize_response(response)
        raw_call = RawCall(request=request, response=serialized_response)

        logger.info(
            "generation.anthropic sources=%s context_doc_ids=%s input_tokens=%d output_tokens=%d latency_s=%.3f",
            result.sources,
            [c.doc_id for c in context_chunks],
            input_tokens,
            output_tokens,
            latency,
        )
        return result, stats, raw_call

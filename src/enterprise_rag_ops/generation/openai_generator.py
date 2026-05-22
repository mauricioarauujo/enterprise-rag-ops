"""OpenAI-backed `Generator` using structured outputs (FR-3, RQ-11).

Calls `client.chat.completions.create` with
`response_format={"type": "json_schema", "json_schema": ..., "strict": true}`
so the response is schema-validated server-side. Defensively re-validates the
returned JSON through Pydantic so any drift surfaces as a typed
`ValidationError`, not an opaque SDK exception (Risk #1 in DESIGN.md).
"""

from __future__ import annotations

import logging
import os

from openai import OpenAI

from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "gpt-5-nano-2025-08-07"


class OpenAIGenerator:
    """`Generator` implementation calling OpenAI structured outputs (FR-3).

    Default model is `gpt-5-nano-2025-08-07`; override via env var `RAG_GEN_MODEL`.
    The CLI does not expose a model flag in Phase 3 — env var only — to keep the
    surface narrow.

    Temperature is left at the model default. GPT-5-class models reject an
    explicit `temperature` other than 1, so we do not send one (NFR-4
    reproducibility is carried by the deterministic prompt builder; a model-level
    determinism strategy — seed or a temperature-capable model — is an ADR-005
    concern for Sprint 2's eval harness).
    """

    def __init__(self, model: str | None = None, client: OpenAI | None = None) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                # NFR-7: clean error, not an SDK stack trace.
                raise RuntimeError(
                    "OPENAI_API_KEY is not set — required for OpenAIGenerator. "
                    "Set it in your shell or .env before running `make smoke` "
                    "or the `rag-ask` CLI."
                )
            client = OpenAI()
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL", DEFAULT_MODEL)

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Call OpenAI and return a validated `AnswerWithSources`."""
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(context_chunks, question)

        # Single source of truth: AnswerWithSources owns the JSON schema.
        json_schema = {
            "name": "AnswerWithSources",
            "schema": AnswerWithSources.model_json_schema(),
            "strict": True,
        }

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_schema", "json_schema": json_schema},
        )
        raw = response.choices[0].message.content or ""
        result = AnswerWithSources.model_validate_json(raw)
        logger.info(
            "generation.openai sources=%s context_doc_ids=%s",
            result.sources,
            [c.doc_id for c in context_chunks],
        )
        return result

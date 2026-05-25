"""`rag-ask` — end-to-end question → AnswerWithSources JSON (FR-9).

The empty-retrieval short-circuit (FR-8) lives here, before any context
assembly or `Generator` call — no LLM request is issued in the abstention
branch (AC-8).
"""

from __future__ import annotations

import argparse
import logging
import sys

from enterprise_rag_ops.generation.context import ContextAssembler
from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator
from enterprise_rag_ops.generation.schema import ABSTAIN_ANSWER, AnswerWithSources
from enterprise_rag_ops.retrieval import config, pipeline
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore

logger = logging.getLogger("enterprise_rag_ops.generation.cli")

# Re-exported from `schema` (the canonical home) so existing importers — including
# the eval harness, which imports it from here per NFR-5 — keep working unchanged.
__all__ = ["ABSTAIN_ANSWER", "main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-ask",
        description="Answer a question using the built RAG index + OpenAI generation.",
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="The question to answer. Reads from stdin if omitted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints AnswerWithSources JSON."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    question = args.question if args.question is not None else sys.stdin.read().strip()
    if not question:
        parser.error("question must be provided via argv or stdin")

    retriever = pipeline.load_retriever()
    chunk_hits = retriever.retrieve_chunks(question)

    if not chunk_hits:
        # FR-8 abstention short-circuit — no Generator call.
        result = AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[])
        logger.info("generation.cli abstain doc_ids=[] sources=[]")
        print(result.model_dump_json())
        return 0

    store = LanceDBStore.open(config.LANCEDB_DIR)
    context_chunks = ContextAssembler(store=store).assemble(chunk_hits)

    result = OpenAIGenerator().generate(context_chunks=context_chunks, question=question)
    logger.info(
        "generation.cli context_doc_ids=%s sources=%s",
        [c.doc_id for c in context_chunks],
        result.sources,
    )
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

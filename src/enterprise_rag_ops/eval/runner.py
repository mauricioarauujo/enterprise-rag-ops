"""Orchestration runner for multi-model RAG evaluation sweeps (FR-5).

Loads the retriever once, runs question sets sequentially or concurrently across
different generator configurations, timing each API call and calculating USD costs.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from enterprise_rag_ops.eval.config import RunConfig
from enterprise_rag_ops.eval.openai_judge import OpenAIJudge
from enterprise_rag_ops.eval.questions import Question, load_questions
from enterprise_rag_ops.eval.records import (
    CallStats,
    EvalRecord,
    GenAiFields,
    GenAiRequest,
    compute_cost_usd,
)
from enterprise_rag_ops.eval.retrieval_metrics import deduplicate_ranked_ids
from enterprise_rag_ops.generation.anthropic_generator import AnthropicGenerator
from enterprise_rag_ops.generation.cli import ABSTAIN_ANSWER
from enterprise_rag_ops.generation.context import ContextAssembler
from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval import config as retrieval_config
from enterprise_rag_ops.retrieval import pipeline
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore

logger = logging.getLogger("enterprise_rag_ops.eval.runner")

# Single source of truth for generator mappings (micro-decision 1)
_GENERATOR_FACTORY = {
    "openai": OpenAIGenerator,
    "anthropic": AnthropicGenerator,
}


def run_evaluation(
    config: RunConfig,
    generator_classes: dict[str, type] | None = None,
    judge_class: type | None = None,
    concurrency: int = 1,
) -> Path:
    """Run the evaluation sweep according to the RunConfig.

    Loads the retriever exactly once (Q6, AC-7), fails fast if index is missing (FR-10, AC-11),
    and halts if total USD cost exceeds cost_ceiling_usd (FR-13, AC-16).
    """
    # 1. Fail-fast guard (FR-10, AC-11)
    if not (
        retrieval_config.BM25_INDEX_DIR.exists()
        and retrieval_config.LANCEDB_DIR.exists()
        and retrieval_config.CHUNK_ORDER_PATH.exists()
    ):
        raise RuntimeError(
            "Gold-aware index artifacts are missing. Please run `make build-index-gold` first."
        )

    # Resolve factories
    gen_factory = generator_classes or _GENERATOR_FACTORY
    resolved_judge_class = judge_class or OpenAIJudge

    # Load retriever once (Q6, AC-7)
    logger.info("Loading retriever (reused across all models)...")
    retriever = pipeline.load_retriever()

    # Try to extract the vector store from retriever, fallback to opening it
    store = getattr(retriever, "_vector_store", None)
    if store is None:
        store = LanceDBStore.open(retrieval_config.LANCEDB_DIR)

    # Open the output JSONL file
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{config.run_id}.jsonl"

    # Track cost and execution state
    total_cost_usd = 0.0
    halt_run = False
    write_lock = threading.Lock()
    cost_lock = threading.Lock()

    # Load questions (limit flows straight through - FR-5)
    questions = list(load_questions(limit=config.limit))
    logger.info("Loaded %d questions for evaluation.", len(questions))

    # Open file for writing
    with open(output_path, "w", encoding="utf-8") as f:
        for model in config.models:
            if halt_run:
                break

            generator_cls = gen_factory.get(model.system)
            if not generator_cls:
                raise ValueError(f"Unsupported system type: {model.system}")

            logger.info("Starting evaluation for model: %s (%s)", model.model_id, model.system)

            # Instantiate generator and judge
            generator = generator_cls(model=model.model_id)
            judge = resolved_judge_class(model=config.judge_model)

            def process_one(q: Question, model=model, generator=generator, judge=judge) -> None:
                nonlocal total_cost_usd, halt_run

                # Read shared halt/ceiling state under the lock that owns it — bare reads
                # of `halt_run` / `total_cost_usd` would race under `--concurrency > 1`.
                with cost_lock:
                    if halt_run or (
                        config.cost_ceiling_usd is not None
                        and total_cost_usd > config.cost_ceiling_usd
                    ):
                        return

                # 1. Retrieve chunks
                chunk_hits = retriever.retrieve_chunks(q.question, top_k=config.k)
                retrieval_ranked_ids = deduplicate_ranked_ids([cid for cid, _, _ in chunk_hits])

                did_abstain_retrieval = len(chunk_hits) == 0

                # 2. Assemble and generate
                if did_abstain_retrieval:
                    answer = AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[])
                    gen_stats = CallStats(
                        input_tokens=0,
                        output_tokens=0,
                        latency_s=0.0,
                        model=model.model_id,
                        system=model.system,
                        cost_usd=0.0,
                    )
                    ctx_chunks = []
                else:
                    ctx_chunks = ContextAssembler(store).assemble(chunk_hits)
                    answer, gen_stats = generator.generate_with_stats(ctx_chunks, q.question)

                # 3. Judge the response
                verdict, judge_stats = judge.judge_with_stats(
                    question=q.question,
                    answer_with_sources=answer,
                    answer_facts=q.answer_facts,
                    retrieved_docs=ctx_chunks,
                )

                # 4. Cost accounting (FR-8)
                gen_price = config.prices.get(gen_stats.model)
                gen_stats.cost_usd = compute_cost_usd(gen_stats, gen_price)

                judge_price = config.prices.get(judge_stats.model)
                judge_stats.cost_usd = compute_cost_usd(judge_stats, judge_price)

                call_cost = (gen_stats.cost_usd or 0.0) + (judge_stats.cost_usd or 0.0)

                # Accumulate cost and decide write-eligibility under one lock so the
                # ceiling check and `halt_run` flip stay consistent under concurrency.
                with cost_lock:
                    cost_before = total_cost_usd
                    total_cost_usd += call_cost
                    crossed_now = (
                        config.cost_ceiling_usd is not None
                        and cost_before <= config.cost_ceiling_usd
                        and total_cost_usd > config.cost_ceiling_usd
                    )
                    if crossed_now:
                        logger.warning(
                            "Cost ceiling of %.2f USD exceeded (current total: %.4f USD). Halting run.",
                            config.cost_ceiling_usd,
                            total_cost_usd,
                        )
                        halt_run = True
                    # Write this record if we haven't halted, or if it is the one that
                    # crossed the ceiling (so the boundary record is never lost).
                    should_write = not halt_run or crossed_now

                did_abstain_e2e = answer.answer == ABSTAIN_ANSWER and len(answer.sources) == 0

                # 5. Build EvalRecord
                record = EvalRecord(
                    question_id=q.question_id,
                    category=q.category,
                    run_id=config.run_id,
                    k=config.k,
                    gen_ai=GenAiFields(
                        request=GenAiRequest(model=model.model_id),
                        system=model.system,
                    ),
                    generation=gen_stats,
                    judge=judge_stats,
                    answer=answer.answer,
                    sources=answer.sources,
                    fact_recall=verdict.fact_recall,
                    fact_precision=verdict.fact_precision,
                    faithfulness_ratio=verdict.faithfulness_ratio,
                    retrieval_ranked_ids=retrieval_ranked_ids,
                    did_abstain_retrieval=did_abstain_retrieval,
                    did_abstain_e2e=did_abstain_e2e,
                )

                # 6. Flush record to JSONL (crash-safe checkpoint, Decision 3-C / AC-2)
                if should_write:
                    with write_lock:
                        f.write(record.model_dump_json() + "\n")
                        f.flush()

            # Execute run depending on concurrency settings (FR-14)
            if concurrency > 1:
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    # Consume the iterator so a worker exception propagates to the
                    # caller instead of being silently swallowed (a discarded
                    # `executor.map` result hides crashes and yields a short JSONL).
                    for _ in executor.map(process_one, questions):
                        pass
            else:
                for q in questions:
                    process_one(q)
                    if halt_run:
                        break

    return output_path

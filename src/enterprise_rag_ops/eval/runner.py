"""Orchestration runner for multi-model RAG evaluation sweeps (FR-5).

Loads the retriever once, runs question sets sequentially or concurrently across
different generator configurations, timing each API call and calculating USD costs.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

import anthropic
import httpx
import openai
from pydantic import ValidationError

from enterprise_rag_ops.eval.bronze import BronzeWriter
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
from enterprise_rag_ops.generation.gemini_generator import GeminiGenerator
from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator
from enterprise_rag_ops.generation.router_generator import RouterGenerator
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval import config as retrieval_config
from enterprise_rag_ops.retrieval import pipeline
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore

logger = logging.getLogger("enterprise_rag_ops.eval.runner")

try:  # google-genai is a hard dependency; guard import only to stay robust to SDK reshuffles
    from google.genai import errors as _genai_errors

    _GOOGLE_TRANSIENT: tuple[type[BaseException], ...] = (_genai_errors.ServerError,)
except Exception:  # pragma: no cover
    _GOOGLE_TRANSIENT = ()

# Transient API/network failures a sweep should survive by leaving a resumable GAP rather
# than crashing the whole run (one timeout across ~2500 calls otherwise kills everything).
# Deliberately EXCLUDES auth/4xx config errors (e.g. openai.AuthenticationError, ClientError)
# and plain bugs (RuntimeError) — those still propagate and crash loudly on the first call,
# so a misconfigured run fails fast instead of silently skipping every question.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,  # base of openai.APITimeoutError
    openai.InternalServerError,
    openai.RateLimitError,
    anthropic.APIConnectionError,  # base of anthropic.APITimeoutError
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    httpx.TransportError,  # RemoteProtocolError, TimeoutException, ConnectError, ...
    *_GOOGLE_TRANSIENT,
)

# Single source of truth for generator mappings (micro-decision 1)
_GENERATOR_FACTORY = {
    "openai": OpenAIGenerator,
    "anthropic": AnthropicGenerator,
    "google": GeminiGenerator,
}


class _SweepUnit(NamedTuple):
    """One row in the sweep: a model identity + its constructed generator.

    Generalises `ModelConfig` so the loop body is generator-source-agnostic. Real models
    map 1:1 from `config.models`; the cost-router (FR-8) is appended as a synthetic
    ``("router", "router")`` unit — it is NOT a `ModelConfig`, whose `system` Literal
    excludes ``"router"``.
    """

    model_id: str
    system: str
    generator: object


# FR-10: dirs existing is not enough — a *plain* index passes the existence check but
# contains ≈none of the benchmark's gold docs, so retrieval recall is ~0% and every score
# is meaningless. A gold-aware corpus contains every answerable question's expected_doc_ids
# by construction. Sample the first questions, take their gold docs, and require a majority
# to be present in the built corpus — this cleanly separates a gold-aware build (~100%
# present) from a plain one (~0%) while tolerating a few legitimately-missing docs.
_GOLD_SAMPLE_SIZE = 50
_GOLD_PRESENCE_MIN_FRACTION = 0.5


def _assert_gold_aware_index() -> None:
    """Raise unless the built corpus actually contains the benchmark's gold docs (FR-10).

    Reads the chunk-order sidecar (chunk IDs → doc IDs via the canonical ``::`` split),
    samples the gold ``expected_doc_ids`` of the first questions, and fails fast if too
    few are present — a non-gold index would otherwise silently produce junk scores.
    """
    chunk_order = json.loads(retrieval_config.CHUNK_ORDER_PATH.read_text(encoding="utf-8"))
    corpus_doc_ids = set(deduplicate_ranked_ids(chunk_order))
    gold_doc_ids = {
        doc_id for q in load_questions(limit=_GOLD_SAMPLE_SIZE) for doc_id in q.expected_doc_ids
    }
    if not gold_doc_ids:
        return  # no answerable questions sampled — nothing to verify
    present_fraction = len(gold_doc_ids & corpus_doc_ids) / len(gold_doc_ids)
    if present_fraction < _GOLD_PRESENCE_MIN_FRACTION:
        raise RuntimeError(
            f"Index exists but is not gold-aware: only {present_fraction:.0%} of sampled "
            f"gold docs are in the corpus (need >={_GOLD_PRESENCE_MIN_FRACTION:.0%}). "
            "A plain index yields ~0% retrieval recall and meaningless scores. Run "
            "`make build-index-gold` to rebuild the corpus from the benchmark's "
            "expected_doc_ids + distractors."
        )


def run_evaluation(
    config: RunConfig,
    generator_classes: dict[str, type] | None = None,
    judge_class: type | None = None,
    concurrency: int = 1,
    resume: bool = False,
) -> Path:
    """Run the evaluation sweep according to the RunConfig.

    Loads the retriever exactly once (Q6, AC-7), fails fast if the gold-aware index is
    missing or not gold-aware (FR-10, AC-11), and halts if total USD cost exceeds
    cost_ceiling_usd (FR-13, AC-16).

    Robustness: a transient API/network error on one question (see ``_TRANSIENT_ERRORS``)
    is logged and skipped — it leaves a gap rather than killing the whole sweep. With
    ``resume=True`` an existing ``{run_id}.jsonl`` is appended to: every ``(system,
    question_id)`` already present is skipped and only the gaps are (re)run, so re-running
    converges to a complete sweep. ``resume=False`` (default) truncates and starts fresh,
    preserving the original contract. Non-transient errors (auth/4xx, bugs) still propagate.
    """
    # 1. Fail-fast guard (FR-10, AC-11): artifacts present *and* the corpus is gold-aware.
    if not (
        retrieval_config.BM25_INDEX_DIR.exists()
        and retrieval_config.LANCEDB_DIR.exists()
        and retrieval_config.CHUNK_ORDER_PATH.exists()
    ):
        raise RuntimeError(
            "Gold-aware index artifacts are missing. Please run `make build-index-gold` first."
        )
    _assert_gold_aware_index()

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
    failed_count = 0  # questions skipped this run due to a transient API/network error
    write_lock = threading.Lock()
    cost_lock = threading.Lock()
    fail_lock = threading.Lock()
    # The shared retriever's BGE-M3 encoder (torch/MPS) is not thread-safe; concurrent
    # encodes abort the process. Serialize the (fast) encode under this lock — the slow
    # LLM calls still run concurrently, which is where --concurrency actually pays off.
    retrieve_lock = threading.Lock()
    bronze_writer = BronzeWriter(run_id=config.run_id) if config.persist_bronze else None

    # Resume (idempotent re-run): skip every (system, question_id) already in the JSONL and
    # append only the gaps, so a sweep killed mid-run (or with transient-error gaps) converges
    # to complete on re-run. Prior cost is re-accumulated so the ceiling stays meaningful.
    completed: set[tuple[str, str]] = set()
    resume_active = resume and output_path.exists()
    if resume_active:
        for line in output_path.read_text().splitlines():
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a truncated final line from a hard crash mid-write
            completed.add((prior["gen_ai"]["system"], prior["question_id"]))
            total_cost_usd += (prior["generation"].get("cost_usd") or 0.0) + (
                prior["judge"].get("cost_usd") or 0.0
            )
        logger.info(
            "Resume: %d records already complete in %s; %.4f USD prior cost loaded.",
            len(completed),
            output_path,
            total_cost_usd,
        )
    file_mode = "a" if resume_active else "w"

    # Load questions (limit flows straight through - FR-5)
    questions = list(load_questions(limit=config.limit))
    logger.info("Loaded %d questions for evaluation.", len(questions))

    # Build the sweep: one _SweepUnit per real model, plus the synthetic router row (FR-8).
    sweep_units: list[_SweepUnit] = []
    for model in config.models:
        generator_cls = gen_factory.get(model.system)
        if not generator_cls:
            raise ValueError(f"Unsupported system type: {model.system}")
        sweep_units.append(
            _SweepUnit(model.model_id, model.system, generator_cls(model=model.model_id))
        )

    # FR-8: append the cost-router as a synthetic ("router","router") row. Its cheap/strong
    # sub-generators resolve through the SAME gen_factory seam the real models use — in
    # production "google"->GeminiGenerator and "anthropic"->AnthropicGenerator (FR-8), while
    # tests inject fakes through the same factory. The router is never a ModelConfig (C-2).
    if config.router is not None:
        router = config.router
        cheap_cls = gen_factory.get("google")
        strong_cls = gen_factory.get("anthropic")
        if cheap_cls is None or strong_cls is None:
            raise ValueError(
                "RouterGenerator requires 'google' (cheap) and 'anthropic' (strong) "
                "entries in the generator factory."
            )
        sweep_units.append(
            _SweepUnit(
                "router",
                "router",
                RouterGenerator(
                    cheap=cheap_cls(model=router.cheap_model_id),
                    strong=strong_cls(model=router.strong_model_id),
                    prices=config.prices,
                    cheap_model_id=router.cheap_model_id,
                    strong_model_id=router.strong_model_id,
                    threshold=router.threshold,
                ),
            )
        )

    # Open file for writing (append on resume so prior records are preserved).
    with open(output_path, file_mode, encoding="utf-8") as f:
        for unit in sweep_units:
            if halt_run:
                break

            logger.info("Starting evaluation for model: %s (%s)", unit.model_id, unit.system)

            # Instantiate the judge (the generator is already built into the sweep unit).
            judge = resolved_judge_class(model=config.judge_model)

            def process_one(q: Question, model=unit, generator=unit.generator, judge=judge) -> None:
                nonlocal total_cost_usd, halt_run, failed_count

                # Skip questions already completed for this system (resume — idempotent).
                if (model.system, q.question_id) in completed:
                    return

                # Read shared halt/ceiling state under the lock that owns it — bare reads
                # of `halt_run` / `total_cost_usd` would race under `--concurrency > 1`.
                with cost_lock:
                    if halt_run or (
                        config.cost_ceiling_usd is not None
                        and total_cost_usd > config.cost_ceiling_usd
                    ):
                        return

                # 1. Retrieve chunks (encode serialized — see retrieve_lock above)
                with retrieve_lock:
                    chunk_hits = retriever.retrieve_chunks(q.question, top_k=config.k)
                retrieval_ranked_ids = deduplicate_ranked_ids([cid for cid, _, _ in chunk_hits])

                did_abstain_retrieval = len(chunk_hits) == 0

                # Generation + judging are the network calls. A transient API/network error
                # on either is skipped (leaving a resumable gap) instead of killing the whole
                # sweep; non-transient errors (auth/4xx, bugs) propagate and fail fast.
                try:
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
                        gen_raw = None
                    else:
                        ctx_chunks = ContextAssembler(store).assemble(chunk_hits)
                        answer, gen_stats, gen_raw = generator.generate_with_stats(
                            ctx_chunks, q.question
                        )

                    # 3. Judge the response
                    verdict, judge_stats, judge_raw = judge.judge_with_stats(
                        question=q.question,
                        answer_with_sources=answer,
                        answer_facts=q.answer_facts,
                        retrieved_docs=ctx_chunks,
                    )
                except _TRANSIENT_ERRORS as exc:
                    with fail_lock:
                        failed_count += 1
                    logger.warning(
                        "Transient error on %s [%s/%s] — skipping (resume to retry): %s: %s",
                        q.question_id,
                        model.system,
                        model.model_id,
                        type(exc).__name__,
                        exc,
                    )
                    return
                except ValidationError as exc:
                    # A model returned structured output that fails its schema (e.g.
                    # AnswerWithSources missing `sources`, or a malformed judge verdict). Like a
                    # transient API error, this is a per-question fault that must not crash a
                    # 1500-call sweep — skip it as a resumable gap. A *systematic* schema bug
                    # surfaces as "every question skipped, resume never converges" (the
                    # end-of-run warning), which is visible, not silent.
                    with fail_lock:
                        failed_count += 1
                    logger.warning(
                        "Malformed model output on %s [%s/%s] — skipping (resume to retry): %s: %s",
                        q.question_id,
                        model.system,
                        model.model_id,
                        type(exc).__name__,
                        exc,
                    )
                    return

                # 4. Cost accounting (FR-8, FR-9). Guard: a generator that already set
                # cost_usd owns its cost and the runner treats it as final — the router
                # (FR-5) manufactures the true combined cheap+strong cost, and the
                # retrieval-abstain stub pre-sets 0.0. Every single-model generator returns
                # cost_usd=None, so the body runs exactly as before (NFR-4, AC-10).
                if gen_stats.cost_usd is None:
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
                    per_fact=verdict.per_fact,
                    per_citation=verdict.per_citation,
                    retrieval_ranked_ids=retrieval_ranked_ids,
                    did_abstain_retrieval=did_abstain_retrieval,
                    did_abstain_e2e=did_abstain_e2e,
                )

                # 6. Flush record to JSONL (crash-safe checkpoint, Decision 3-C / AC-2)
                if should_write:
                    if bronze_writer is not None:
                        if gen_raw is not None:
                            bronze_writer.write(
                                q.question_id,
                                model.model_id,
                                "gen",
                                {
                                    "schema_version": 1,
                                    "meta": {
                                        "run_id": config.run_id,
                                        "question_id": q.question_id,
                                        "model": model.model_id,
                                        "system": model.system,
                                        "call_type": "gen",
                                    },
                                    "request": gen_raw.request,
                                    "response": gen_raw.response,
                                },
                            )
                        # The judge always runs (unlike generation, which is skipped on a
                        # retrieval abstain), so judge_raw is never None here.
                        bronze_writer.write(
                            q.question_id,
                            model.model_id,
                            "judge",
                            {
                                "schema_version": 1,
                                "meta": {
                                    "run_id": config.run_id,
                                    "question_id": q.question_id,
                                    "model": model.model_id,
                                    "system": "openai",
                                    "call_type": "judge",
                                },
                                "request": judge_raw.request,
                                "response": judge_raw.response,
                            },
                        )

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

    if failed_count:
        logger.warning(
            "%d question(s) hit a transient error or malformed model output and were skipped "
            "this run. Re-run with `--resume` to fill the gaps (the overlap guard requires "
            "every system complete).",
            failed_count,
        )
    return output_path

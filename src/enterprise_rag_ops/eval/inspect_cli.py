"""Command-line interface to inspect evaluation records and join with gold questions.

Provides the `rag-inspect` CLI tool to query baseline results for a question ID
and compare answers, retrieval metrics, and failure modes across models.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from enterprise_rag_ops.eval.questions import Question, load_questions
from enterprise_rag_ops.eval.records import EvalRecord


@dataclass(frozen=True, slots=True)
class ModelInspection:
    """Detailed evaluation result for a single model on a question."""

    model: str
    answer: str
    sources: list[str]
    retrieval_ranked_ids: list[str]
    gold_overlap: set[str]
    failure_mode: str | None
    fact_recall: float | None
    faithfulness_ratio: float | None
    did_abstain_retrieval: bool
    did_abstain_e2e: bool
    retrieval_succeeded: bool


@dataclass(frozen=True, slots=True)
class InspectResult:
    """The structured result of joining EvalRecords with a gold Question."""

    question_id: str
    question_text: str
    answer_facts: list[str]
    expected_doc_ids: list[str]
    models: list[ModelInspection]


def inspect_question(
    records: list[EvalRecord],
    question: Question,
    model: str | None = None,
) -> InspectResult:
    """Pure analysis function joining records for a question with its gold Question.

    Filters records to the target question_id, computes gold retrieval overlap,
    and returns a structured dataclass representation.
    """
    matching_records = [r for r in records if r.question_id == question.question_id]

    if model is not None:
        model_lower = model.lower()
        matching_records = [
            r for r in matching_records if model_lower in r.gen_ai.request.model.lower()
        ]

    expected_docs_set = set(question.expected_doc_ids)
    model_inspections: list[ModelInspection] = []

    for rec in matching_records:
        ret_ids = rec.retrieval_ranked_ids or []
        gold_overlap = set(ret_ids) & expected_docs_set
        retrieval_succeeded = len(gold_overlap) > 0

        model_inspections.append(
            ModelInspection(
                model=rec.gen_ai.request.model,
                answer=rec.answer,
                sources=rec.sources,
                retrieval_ranked_ids=ret_ids,
                gold_overlap=gold_overlap,
                failure_mode=rec.failure_mode,
                fact_recall=rec.fact_recall,
                faithfulness_ratio=rec.faithfulness_ratio,
                did_abstain_retrieval=rec.did_abstain_retrieval,
                did_abstain_e2e=rec.did_abstain_e2e,
                retrieval_succeeded=retrieval_succeeded,
            )
        )

    return InspectResult(
        question_id=question.question_id,
        question_text=question.question,
        answer_facts=question.answer_facts,
        expected_doc_ids=question.expected_doc_ids,
        models=model_inspections,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for rag-inspect."""
    parser = argparse.ArgumentParser(
        prog="rag-inspect",
        description="Inspect evaluation records and join with gold questions.",
    )
    parser.add_argument(
        "--question-id",
        required=True,
        help="The question ID to inspect (e.g., qst_0001).",
    )
    parser.add_argument(
        "--results",
        default="results/baseline.jsonl",
        help="Path to the JSONL evaluation results file (default: results/baseline.jsonl).",
    )
    parser.add_argument(
        "--model",
        help="Optional case-insensitive substring filter for model names.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints errors to stderr."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    results_path = Path(args.results)

    try:
        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        # Load gold question
        questions = list(load_questions(question_ids=[args.question_id]))
        if not questions:
            raise ValueError(f"Question ID '{args.question_id}' not found in gold dataset.")
        question = questions[0]

        # Load matching records
        records: list[EvalRecord] = []
        with open(results_path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = EvalRecord.model_validate_json(stripped)
                except Exception as e:
                    print(f"Error parsing JSONL on line {line_no}: {e}", file=sys.stderr)
                    return 1

                if record.question_id == args.question_id:
                    records.append(record)

        # Run pure inspect function
        result = inspect_question(records, question, model=args.model)

        # Format and output results to stdout
        print("=" * 80)
        print(f"QUESTION ID: {result.question_id}")
        print("=" * 80)
        print(f"Question Text:\n  {result.question_text}\n")
        print("Gold Facts:")
        for fact in result.answer_facts:
            print(f"  - {fact}")
        print(f"\nExpected Doc IDs:\n  {', '.join(result.expected_doc_ids)}\n")

        for m in result.models:
            print("-" * 80)
            print(f"MODEL: {m.model}")
            print("-" * 80)
            print(f"Answer:\n  {m.answer}\n")
            print(f"Sources: {', '.join(m.sources)}")

            # Highlight gold overlap with '*'
            marked_retrieval_ids = [
                f"{rid}*" if rid in result.expected_doc_ids else rid
                for rid in m.retrieval_ranked_ids
            ]
            print(f"Retrieval Ranked IDs: {', '.join(marked_retrieval_ids)}")
            print(f"Gold Overlap Count  : {len(m.gold_overlap)} / {len(result.expected_doc_ids)}")

            print("\nAbstention Flags:")
            print(f"  did_abstain_retrieval: {m.did_abstain_retrieval}")
            print(f"  did_abstain_e2e      : {m.did_abstain_e2e}")
            print(f"  retrieval_succeeded  : {m.retrieval_succeeded}")

            print(f"\nFailure Mode       : {m.failure_mode}")
            print(f"Fact Recall        : {m.fact_recall}")
            print(f"Faithfulness Ratio : {m.faithfulness_ratio}")
            print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

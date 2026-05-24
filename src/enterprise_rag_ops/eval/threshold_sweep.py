"""Standalone script to sweep the retrieval-level abstention threshold (Should tier, AC-15).

Sweeps thresholds from 0.30 to 0.65 (step 0.05) to find the optimal operating point,
reporting precision, recall, and F1-score of abstention.
"""

from __future__ import annotations

import logging
import sys

from enterprise_rag_ops.eval.abstention import compute_abstention_metrics
from enterprise_rag_ops.eval.questions import load_questions
from enterprise_rag_ops.retrieval.pipeline import load_retriever

logger = logging.getLogger("enterprise_rag_ops.eval.threshold_sweep")


def run_sweep() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("Loading questions and retriever...")
    questions = list(load_questions())
    retriever = load_retriever()

    logger.info(f"Running dense search for {len(questions)} queries...")
    best_scores = {}
    for i, q in enumerate(questions):
        if i > 0 and i % 100 == 0:
            logger.info(f"  Processed {i}/{len(questions)} queries...")
        # Get the best dense hit score for each question
        query_vector = retriever._embedder.encode([q.question])[0]
        dense_hits = retriever._vector_store.dense_search(query_vector=query_vector, k=1)
        best_scores[q.question_id] = dense_hits[0][1] if dense_hits else -1.0

    print("\n--- Abstention Threshold Sweep (0.30 - 0.65) ---")
    print(
        f"{'Threshold':<10} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10} | {'TP/FP/FN/TN':<15}"
    )
    print("-" * 65)

    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
    for t in thresholds:
        did_abstain_map = {qid: score < t for qid, score in best_scores.items()}
        metrics = compute_abstention_metrics(questions, did_abstain_map)

        # Calculate F1
        p = metrics["precision"]
        r = metrics["recall"]
        tp = metrics["tp"]
        fp = metrics["fp"]
        fn = metrics["fn"]
        tn = metrics["tn"]

        f1 = (2 * p * r) / (p + r) if p and r and (p + r) > 0 else 0.0

        p_str = f"{p:.4f}" if p is not None else "None"
        r_str = f"{r:.4f}" if r is not None else "None"
        f1_str = f"{f1:.4f}" if f1 else "None"

        print(
            f"{t:<10.2f} | {p_str:<10} | {r_str:<10} | {f1_str:<10} | {f'{tp}/{fp}/{fn}/{tn}':<15}"
        )


if __name__ == "__main__":
    sys.exit(run_sweep())

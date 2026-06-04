"""Capture the retrieval (RRF) score per gold question — one of the three escalation
signals validated in sprint-7/phase-1 (alongside verbalized confidence + abstention).

`results/baseline.jsonl` persists only `retrieval_ranked_ids` (doc ids), NOT the fused
scores, so this re-runs retrieval locally (no LLM, no API spend) over the gold questions
and records, per `question_id`:

    retrieval_top_score : the top fused RRF score (higher = stronger retrieval)
    retrieval_margin    : top1 - top2 fused score (separation of the best hit)
    n_hits              : number of retrieved docs (0 == retrieval abstained)

Output: results/retrieval-scores.jsonl. Dev one-shot — not a product CLI.

Run (index must be built — `make build-index-gold`):
    uv run python scripts/capture_retrieval_scores.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from enterprise_rag_ops.eval.questions import load_questions
from enterprise_rag_ops.retrieval import pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("capture_retrieval_scores")

TOP_K = 10  # matches configs/gemini-confidence.yaml `k`
OUT_PATH = Path("results/retrieval-scores.jsonl")


def main() -> int:
    questions = list(load_questions(limit=None))
    logger.info("Loaded %d gold questions", len(questions))
    retriever = pipeline.load_retriever()

    rows = []
    for i, q in enumerate(questions, start=1):
        hits = retriever.retrieve_chunks(q.question, top_k=TOP_K)  # (chunk_id, doc_id, score)
        if hits:
            top = hits[0][2]
            margin = (hits[0][2] - hits[1][2]) if len(hits) >= 2 else hits[0][2]
        else:
            top = None  # retrieval abstained — no confident match
            margin = None
        rows.append(
            {
                "question_id": q.question_id,
                "retrieval_top_score": top,
                "retrieval_margin": margin,
                "n_hits": len(hits),
            }
        )
        if i % 50 == 0:
            logger.info("  retrieved %d/%d", i, len(questions))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    n_abstain = sum(r["n_hits"] == 0 for r in rows)
    logger.info("Wrote %d rows to %s (%d retrieval-abstentions)", len(rows), OUT_PATH, n_abstain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

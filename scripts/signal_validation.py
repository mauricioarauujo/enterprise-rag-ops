"""Validate the sprint-7/phase-1 escalation signals — does any inference-time signal
separate CORRECT cheap-model answers from incorrect ones? Pure pandas, no live API.

Signals validated (all obtainable on gemini-2.5-flash-lite, which has NO logprobs — ADR-0011):
  1. verbalized confidence  — the model's self-reported confidence (CallStats.confidence_score)
  2. abstention             — did_abstain_e2e (answered=1 as a "likely-correct" proxy)
  3. retrieval RRF score    — top fused retrieval score (scripts/capture_retrieval_scores.py)
  4. hybrid                 — confidence, forced to 0 when the model abstained (free OR-trigger)

Ground truth is same-run: the confidence-run JSONL is classified in place by `rag-classify`,
so `correct = (failure_mode == "correct")` pairs each confidence with ITS OWN answer's
correctness (more correct than joining stale baseline labels).

Discipline (research Q6 / UCCI): a seeded ~20/80 calibration/test split; any reported
threshold is set on calibration, all AUROC/separation metrics on the test split.

Inputs : results/gemini-confidence.jsonl (classified), results/retrieval-scores.jsonl
Outputs: docs/analysis/escalation-signal-validation.md, docs/analysis/escalation-signal-separation.png

Run (after the sweep + `rag-classify` + capture_retrieval_scores.py):
    uv run python scripts/signal_validation.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — write a PNG, no display
import matplotlib.pyplot as plt
import pandas as pd

CONF_PATH = Path("results/gemini-confidence.jsonl")
RETR_PATH = Path("results/retrieval-scores.jsonl")
REPORT_PATH = Path("docs/analysis/escalation-signal-validation.md")
PLOT_PATH = Path("docs/analysis/escalation-signal-separation.png")

SPLIT_SEED = 42
CALIB_FRAC = 0.20
# The verbalized confidence is bimodal at {0, 1} (the cheap model is overconfident), so a
# percentile threshold is degenerate (P25 == 0.0). Operating-point PROCEDURE instead
# (OQ-5: a procedure, not a magic number): escalate unless the model is MAXIMALLY confident
# AND answered — i.e. escalate if confidence < 1.0 OR it abstained. Verified on calibration
# to be non-degenerate, reported on test.
CONF_GATE = 1.0


def _auroc(scores: pd.Series, labels: pd.Series) -> float:
    """AUROC as the Mann-Whitney U statistic (rank-based, pure pandas). Higher `scores`
    should predict label==1. NaN scores are dropped. Returns NaN if a class is empty."""
    df = pd.DataFrame({"s": scores, "y": labels}).dropna()
    n_pos = int((df.y == 1).sum())
    n_neg = int((df.y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = df["s"].rank(method="average")
    sum_pos = ranks[df.y == 1].sum()
    return float((sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _load() -> pd.DataFrame:
    conf_rows = []
    for line in CONF_PATH.open():
        r = json.loads(line)
        fm = r.get("failure_mode")
        conf_rows.append(
            {
                "question_id": r["question_id"],
                "confidence": (r.get("generation") or {}).get("confidence_score"),
                "did_abstain_e2e": r.get("did_abstain_e2e"),
                "failure_mode": fm,
            }
        )
    conf = pd.DataFrame(conf_rows)

    retr = pd.DataFrame([json.loads(line) for line in RETR_PATH.open()])[
        ["question_id", "retrieval_top_score"]
    ]
    df = conf.merge(retr, on="question_id", how="left")

    if df["failure_mode"].isna().any():
        n = int(df["failure_mode"].isna().sum())
        raise SystemExit(
            f"{n} rows have failure_mode=None — run `rag-classify --results {CONF_PATH}` first."
        )

    df["correct"] = (df["failure_mode"] == "correct").astype(int)
    # Signal scores: higher == more likely correct (== less need to escalate).
    df["s_confidence"] = df["confidence"]
    df["s_abstention"] = (~df["did_abstain_e2e"].astype(bool)).astype(float)  # answered=1
    df["s_retrieval"] = df["retrieval_top_score"]
    df["s_hybrid"] = df["confidence"].where(~df["did_abstain_e2e"].astype(bool), 0.0)
    return df


def main() -> int:
    df = _load()
    calib = df.sample(frac=CALIB_FRAC, random_state=SPLIT_SEED)
    test = df.drop(calib.index)

    signals = {
        "verbalized confidence": "s_confidence",
        "abstention (answered)": "s_abstention",
        "retrieval RRF score": "s_retrieval",
        "hybrid (confidence OR abstain)": "s_hybrid",
    }
    aurocs = {name: _auroc(test[col], test["correct"]) for name, col in signals.items()}

    # Operating point (procedure, see CONF_GATE): escalate unless maximally confident AND
    # answered. Calibration confirms it is non-degenerate; escalation rate reported on test.
    calib_gate_rate = float(
        ((calib["s_confidence"] < CONF_GATE) | (calib["did_abstain_e2e"].astype(bool))).mean()
    )
    escalate_test = (test["s_confidence"] < CONF_GATE) | (test["did_abstain_e2e"].astype(bool))
    escalation_rate = float(escalate_test.mean())

    n = len(df)
    base_rate = float(df["correct"].mean())

    # --- separation plot (confidence: correct vs incorrect, test split) ------------------
    PLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    bins = [i / 20 for i in range(21)]
    ax.hist(
        test.loc[test.correct == 1, "s_confidence"].dropna(),
        bins=bins,
        alpha=0.6,
        label="correct",
        color="#2a9d8f",
        density=True,
    )
    ax.hist(
        test.loc[test.correct == 0, "s_confidence"].dropna(),
        bins=bins,
        alpha=0.6,
        label="incorrect",
        color="#e76f51",
        density=True,
    )
    ax.axvline(
        CONF_GATE, color="#264653", linestyle="--", linewidth=1, label="escalate unless == 1.0"
    )
    ax.set_xlabel("verbalized confidence")
    ax.set_ylabel("density")
    ax.set_title("Cheap-model verbalized confidence: correct vs incorrect (test split)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=120)
    plt.close(fig)

    # --- markdown report -----------------------------------------------------------------
    lines = [
        "# Escalation-Signal Validation — sprint-7/phase-1",
        "",
        "> Generated by `scripts/signal_validation.py`. Supporting evidence for ADR-0011.",
        "> **No hard AUROC bar** — these numbers feed a human phase-2 go/no-go judgement call.",
        "",
        "## Setup",
        "",
        "- Cheap model: `gemini-2.5-flash-lite` (NO token logprobs — see ADR-0011).",
        f"- Questions: **{n}**; correct base rate: **{base_rate:.1%}**.",
        '- Labels: same-run `failure_mode == "correct"` (confidence paired with its own answer).',
        f"- Split: seeded {int((1 - CALIB_FRAC) * 100)}/{int(CALIB_FRAC * 100)} "
        f"test/calibration (seed={SPLIT_SEED}); AUROC on the **test** split "
        f"(n={len(test)}); threshold set on calibration only.",
        "",
        "## AUROC — does the signal separate correct from incorrect? (test split)",
        "",
        "AUROC 0.5 = no better than chance; higher = the signal is higher on correct answers.",
        "",
        "| Signal | AUROC |",
        "| ------ | ----- |",
    ]
    for name, val in aurocs.items():
        lines.append(f"| {name} | {val:.3f} |")
    lines += [
        "",
        "## Operating point (illustrative)",
        "",
        "The verbalized confidence is **bimodal at {0, 1}** — the cheap model is overconfident "
        "(among *answered* questions its confidence is ~0.99 whether right or wrong), so a "
        "percentile threshold is degenerate. Operating-point procedure instead: **escalate "
        "unless the model is maximally confident (== 1.0) AND did not abstain.**",
        "",
        f"- Implied **escalation rate**: calibration {calib_gate_rate:.1%}, "
        f"**test {escalation_rate:.1%}** (bounds the phase-2 cost estimate).",
        "",
        "## Separation plot",
        "",
        f"![confidence separation]({PLOT_PATH.name})",
        "",
        "## Reading",
        "",
        "The numbers above are the deliverable; the phase-2 go/no-go is a human call (DEFINE",
        "decision 2). A weak AUROC across all signals is itself a valid, honest finding: it",
        "would mean cost-aware routing cannot beat a single model on this stack via these signals.",
        "",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines))

    print(
        f"n={n} base_rate={base_rate:.3f} escalation_rate(test)={escalation_rate:.3f} "
        f"calib={calib_gate_rate:.3f}"
    )
    for name, val in aurocs.items():
        print(f"  AUROC {name:32} = {val:.3f}")
    print(f"wrote {REPORT_PATH} and {PLOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

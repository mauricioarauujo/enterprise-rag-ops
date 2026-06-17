"""Report rendering functions and templates (FR-7, NFR-2).

Deterministic aggregator and renderer for evaluation results. Outputs both HTML and Markdown
reports with modern, premium styling.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from string import Template

from enterprise_rag_ops.eval.abstention import compute_abstention_metrics
from enterprise_rag_ops.eval.questions import load_questions
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.retrieval_eval import aggregate_retrieval_metrics
from enterprise_rag_ops.eval.root_cause import rollup


def _mean(values: list[float]) -> float | None:
    """Helper to compute mean, returning None if the list is empty (NFR-2)."""
    if not values:
        return None
    return sum(values) / len(values)


def _fmt(val: float | None, pct: bool = False, decimals: int = 3) -> str:
    """Helper to format a value, returning 'N/A' if None (NFR-2)."""
    if val is None:
        return "N/A"
    if pct:
        return f"{val * 100:.1f}%"
    return f"{val:.{decimals}f}"


def generate_report_data(jsonl_path: Path) -> dict:
    """Read evaluation records from JSONL and calculate aggregations for report components (FR-7)."""
    records: list[EvalRecord] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(EvalRecord.model_validate_json(line))

    if not records:
        raise ValueError(f"No records found in {jsonl_path}")

    # Retrieval cut-off the run used (persisted per record; constant across a run).
    k = records[0].k

    # Load and filter questions matching the run
    question_ids = {r.question_id for r in records}
    questions = [q for q in load_questions() if q.question_id in question_ids]

    # Group by model
    model_records = defaultdict(list)
    for r in records:
        model_records[r.gen_ai.request.model].append(r)

    # 1. Summary Metrics
    summary_data = []
    for model_name, recs in model_records.items():
        fact_recall = _mean([r.fact_recall for r in recs if r.fact_recall is not None])
        fact_precision = _mean([r.fact_precision for r in recs if r.fact_precision is not None])
        faithfulness = _mean(
            [r.faithfulness_ratio for r in recs if r.faithfulness_ratio is not None]
        )

        abstain_map = {r.question_id: r.did_abstain_e2e for r in recs}
        abstain_metrics = compute_abstention_metrics(questions, abstain_map)

        summary_data.append(
            {
                "model": model_name,
                "fact_recall": fact_recall,
                "fact_precision": fact_precision,
                "faithfulness": faithfulness,
                "abstain_precision": abstain_metrics["precision"],
                "abstain_recall": abstain_metrics["recall"],
            }
        )

    # 2. Per-category Metrics (across 10 categories)
    # Get all categories present in the run
    categories = sorted({q.category for q in questions})
    category_data = []
    # Root-Cause Attribution (SC-2): per-category, per-model retrieval-gap vs
    # generation-gap split of FAILED facts, parallel to `category_data` (NFR-4 — does
    # not touch the 7-column category table).
    root_cause_data = []

    for cat in categories:
        cat_qs = [q for q in questions if q.category == cat]
        cat_q_ids = {q.question_id for q in cat_qs}

        model_cat_metrics = {}
        for model_name, recs in model_records.items():
            cat_recs = [r for r in recs if r.question_id in cat_q_ids]

            # Retrieval aggregates at the run's k cut-off
            ranked_results = {r.question_id: r.retrieval_ranked_ids for r in cat_recs}
            retrieval_aggs = aggregate_retrieval_metrics(cat_qs, ranked_results, k=k)
            cat_retrieval = retrieval_aggs.get(cat, {})

            # Judge aggregates
            fact_recall = _mean([r.fact_recall for r in cat_recs if r.fact_recall is not None])
            fact_precision = _mean(
                [r.fact_precision for r in cat_recs if r.fact_precision is not None]
            )
            faithfulness = _mean(
                [r.faithfulness_ratio for r in cat_recs if r.faithfulness_ratio is not None]
            )

            model_cat_metrics[model_name] = {
                "retrieval_recall": cat_retrieval.get(f"recall_at_{k}"),
                "retrieval_ndcg": cat_retrieval.get(f"ndcg_at_{k}"),
                "fact_recall": fact_recall,
                "fact_precision": fact_precision,
                "faithfulness": faithfulness,
            }

        category_data.append({"category": cat, "metrics": model_cat_metrics})

        # Root-cause rollups per model for this category (SC-2 / FR-3 / FR-6).
        model_cat_root_cause = {}
        for model_name, recs in model_records.items():
            cat_recs = [r for r in recs if r.question_id in cat_q_ids]
            agg_retrieval = 0
            agg_generation = 0
            any_evidence = False
            for r in cat_recs:
                rc = rollup(r)
                if rc.has_per_fact:
                    any_evidence = True
                    agg_retrieval += rc.retrieval_gap
                    agg_generation += rc.generation_gap
            denom = agg_retrieval + agg_generation
            # FR-6 / Decision D: no per-fact evidence at all -> None (N/A); evidence with
            # zero gaps -> 0.0 (0.0%); otherwise the retrieval-gap share among failed facts.
            if not any_evidence:
                retrieval_gap_pct = None
            elif denom == 0:
                retrieval_gap_pct = 0.0
            else:
                retrieval_gap_pct = agg_retrieval / denom
            model_cat_root_cause[model_name] = {
                "retrieval_gap": agg_retrieval,
                "generation_gap": agg_generation,
                "retrieval_gap_pct": retrieval_gap_pct,
                "has_evidence": any_evidence,
            }
        root_cause_data.append({"category": cat, "metrics": model_cat_root_cause})

    # 3. Cost & Latency
    cost_data = []
    for model_name, recs in model_records.items():
        has_missing_price = any(
            r.generation.cost_usd is None or r.judge.cost_usd is None for r in recs
        )
        if has_missing_price:
            total_cost = None
        else:
            total_cost = sum(
                (r.generation.cost_usd or 0.0) + (r.judge.cost_usd or 0.0) for r in recs
            )

        mean_latency = _mean([r.generation.latency_s + r.judge.latency_s for r in recs])
        total_tokens = sum(
            r.generation.input_tokens
            + r.generation.output_tokens
            + r.judge.input_tokens
            + r.judge.output_tokens
            for r in recs
        )

        cost_data.append(
            {
                "model": model_name,
                "total_cost": total_cost,
                "mean_latency": mean_latency,
                "total_tokens": total_tokens,
            }
        )

    return {
        "k": k,
        "summary": summary_data,
        "categories": category_data,
        "costs": cost_data,
        "root_cause": root_cause_data,
    }


def render_markdown(data: dict) -> str:
    """Render report to Markdown format (FR-7)."""
    # 1. Summary Table
    md_summary = "| Model | Fact Recall | Fact Precision | Faithfulness | Abstain Precision | Abstain Recall |\n"
    md_summary += "| --- | --- | --- | --- | --- | --- |\n"
    for row in data["summary"]:
        md_summary += (
            f"| **{row['model']}** | {_fmt(row['fact_recall'], pct=True)} | "
            f"{_fmt(row['fact_precision'], pct=True)} | {_fmt(row['faithfulness'], pct=True)} | "
            f"{_fmt(row['abstain_precision'], pct=True)} | {_fmt(row['abstain_recall'], pct=True)} |\n"
        )

    # 2. Category Table
    k = data["k"]
    md_cat = f"| Category | Model | Retrieval Recall@{k} | Retrieval nDCG@{k} | Fact Recall | Fact Precision | Faithfulness |\n"
    md_cat += "| --- | --- | --- | --- | --- | --- | --- |\n"
    for cat_row in data["categories"]:
        first = True
        for model_name, metrics in cat_row["metrics"].items():
            cat_label = f"**{cat_row['category']}**" if first else ""
            md_cat += (
                f"| {cat_label} | {model_name} | {_fmt(metrics['retrieval_recall'], pct=True)} | "
                f"{_fmt(metrics['retrieval_ndcg'])} | {_fmt(metrics['fact_recall'], pct=True)} | "
                f"{_fmt(metrics['fact_precision'], pct=True)} | {_fmt(metrics['faithfulness'], pct=True)} |\n"
            )
            first = False

    # 3. Cost & Latency Table
    md_cost = "| Model | Total Cost (USD) | Mean Latency (sec) | Total Tokens |\n"
    md_cost += "| --- | --- | --- | --- |\n"
    for row in data["costs"]:
        cost_str = f"${row['total_cost']:.4f}" if row["total_cost"] is not None else "N/A"
        md_cost += f"| **{row['model']}** | {cost_str} | {_fmt(row['mean_latency'], decimals=2)}s | {row['total_tokens']:,} |\n"

    # 4. Root-Cause Attribution table (SC-2): retrieval-gap vs generation-gap of FAILED facts.
    md_root_cause = "| Category | Model | Retrieval-Gap (failed facts) | Generation-Gap (failed facts) | Retrieval-Gap % |\n"
    md_root_cause += "| --- | --- | --- | --- | --- |\n"
    for rc_row in data["root_cause"]:
        first = True
        for model_name, rc in rc_row["metrics"].items():
            cat_label = f"**{rc_row['category']}**" if first else ""
            md_root_cause += (
                f"| {cat_label} | {model_name} | {rc['retrieval_gap']} | "
                f"{rc['generation_gap']} | {_fmt(rc['retrieval_gap_pct'], pct=True)} |\n"
            )
            first = False

    template = Template(
        """# RAG Multi-Model Evaluation Baseline Report

## Methodology & Executive Summary
This report presents baseline quality, cost, and latency metrics across our benchmark dataset.
Evaluation is driven by OpenAI and Anthropic generator models, scored against gold annotated facts using an OpenAI judge.

> [!WARNING]
> **Same-Family Judge Bias Caveat**: OpenAIJudge is evaluated on OpenAI model outputs (`gpt-5-nano`). This might inflate scores for OpenAI-family generations due to stylistic and structural alignment. We mitigate this using cross-family generator sweeps (`claude-haiku-4-5`).

## Overall Summary
$summary_table

## Cost & Latency
$cost_table

## Detailed Breakdown Per Category
$category_table

## Root-Cause Attribution
Of the **failed** gold facts (`absent` / `contradicted`), the split between a
*retrieval gap* (no retrieved doc substantiated the fact) and a *generation gap* (the
evidence WAS retrieved but the generator failed to use it). N/A = no per-fact evidence.

$root_cause_table
"""
    )
    return template.substitute(
        summary_table=md_summary,
        cost_table=md_cost,
        category_table=md_cat,
        root_cause_table=md_root_cause,
    )


def render_html(data: dict) -> str:
    """Render report to a premium, styled HTML format (FR-7)."""
    k = data["k"]
    # 1. Summary
    html_summary_rows = ""
    for row in data["summary"]:
        html_summary_rows += f"""
        <tr>
            <td class="model-name"><strong>{row["model"]}</strong></td>
            <td>{_fmt(row["fact_recall"], pct=True)}</td>
            <td>{_fmt(row["fact_precision"], pct=True)}</td>
            <td>{_fmt(row["faithfulness"], pct=True)}</td>
            <td>{_fmt(row["abstain_precision"], pct=True)}</td>
            <td>{_fmt(row["abstain_recall"], pct=True)}</td>
        </tr>"""

    # 2. Category
    html_cat_rows = ""
    for cat_row in data["categories"]:
        first = True
        num_models = len(cat_row["metrics"])
        for model_name, metrics in cat_row["metrics"].items():
            cat_cell = (
                f'<td rowspan="{num_models}" class="category-name">{cat_row["category"]}</td>'
                if first
                else ""
            )
            html_cat_rows += f"""
            <tr>
                {cat_cell}
                <td>{model_name}</td>
                <td>{_fmt(metrics["retrieval_recall"], pct=True)}</td>
                <td>{_fmt(metrics["retrieval_ndcg"])}</td>
                <td>{_fmt(metrics["fact_recall"], pct=True)}</td>
                <td>{_fmt(metrics["fact_precision"], pct=True)}</td>
                <td>{_fmt(metrics["faithfulness"], pct=True)}</td>
            </tr>"""
            first = False

    # 3. Cost
    html_cost_rows = ""
    for row in data["costs"]:
        cost_str = f"${row['total_cost']:.4f}" if row["total_cost"] is not None else "N/A"
        html_cost_rows += f"""
        <tr>
            <td class="model-name"><strong>{row["model"]}</strong></td>
            <td class="cost">{cost_str}</td>
            <td>{_fmt(row["mean_latency"], decimals=2)}s</td>
            <td>{row["total_tokens"]:,}</td>
        </tr>"""

    # 4. Root-Cause Attribution (SC-2) — mirrors the category rowspan pattern.
    html_root_cause_rows = ""
    for rc_row in data["root_cause"]:
        first = True
        num_models = len(rc_row["metrics"])
        for model_name, rc in rc_row["metrics"].items():
            cat_cell = (
                f'<td rowspan="{num_models}" class="category-name">{rc_row["category"]}</td>'
                if first
                else ""
            )
            html_root_cause_rows += f"""
            <tr>
                {cat_cell}
                <td>{model_name}</td>
                <td>{rc["retrieval_gap"]}</td>
                <td>{rc["generation_gap"]}</td>
                <td>{_fmt(rc["retrieval_gap_pct"], pct=True)}</td>
            </tr>"""
            first = False

    template = Template(
        """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>RAG Multi-Model Evaluation Report</title>
    <style>
        :root {
            --bg: #0d0f12;
            --surface: rgba(25, 28, 36, 0.6);
            --border: rgba(255, 255, 255, 0.08);
            --text: #f0f4f8;
            --text-muted: #95a5b5;
            --primary: #58a6ff;
            --accent: #ff7b72;
            --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        body {
            background-color: var(--bg);
            color: var(--text);
            font-family: 'Inter', system-ui, sans-serif;
            margin: 0;
            padding: 40px 20px;
            display: flex;
            justify-content: center;
        }
        .container {
            max-width: 1200px;
            width: 100%;
        }
        h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(45deg, var(--primary), #bc8cff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            color: var(--text-muted);
            font-size: 1.1rem;
            margin-bottom: 40px;
        }
        .card {
            background: var(--surface);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 30px;
            box-shadow: var(--glass-shadow);
        }
        .alert {
            border-left: 4px solid var(--accent);
            background: rgba(255, 123, 114, 0.1);
            padding: 16px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 30px;
        }
        .alert-title {
            font-weight: bold;
            color: var(--accent);
            margin-bottom: 6px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        th {
            text-align: left;
            padding: 12px;
            border-bottom: 2px solid var(--border);
            color: var(--text-muted);
            font-weight: 600;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid var(--border);
        }
        tr:hover {
            background: rgba(255, 255, 255, 0.02);
        }
        .model-name {
            color: var(--primary);
        }
        .category-name {
            font-weight: bold;
            color: var(--text);
            background: rgba(255, 255, 255, 0.01);
            vertical-align: middle;
        }
        .cost {
            font-family: monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>RAG Multi-Model Evaluation Baseline Report</h1>
        <div class="subtitle">Orchestrated baseline quality, cost, and latency metrics across the benchmark set.</div>

        <div class="alert">
            <div class="alert-title">Same-Family Judge Bias Warning</div>
            An OpenAI-family judge (<code>gpt-5-nano</code>) is used to evaluate all answers. This may introduce a stylistic same-family preference for OpenAI generated answers. Cross-family generator checks (<code>claude-haiku-4-5</code>) are included to evaluate this bias.
        </div>

        <div class="card">
            <h2>Overall Summary</h2>
            <table>
                <thead>
                    <tr>
                        <th>Model</th>
                        <th>Fact Recall</th>
                        <th>Fact Precision</th>
                        <th>Faithfulness</th>
                        <th>Abstain Precision</th>
                        <th>Abstain Recall</th>
                    </tr>
                </thead>
                <tbody>
                    $summary_rows
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>Cost & Latency Performance</h2>
            <table>
                <thead>
                    <tr>
                        <th>Model</th>
                        <th>Total Cost (USD)</th>
                        <th>Mean Latency</th>
                        <th>Total Tokens</th>
                    </tr>
                </thead>
                <tbody>
                    $cost_rows
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>Detailed Category breakdown</h2>
            <table>
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Model</th>
                        <th>Retrieval Recall@${cat_k}</th>
                        <th>Retrieval nDCG@${cat_k}</th>
                        <th>Fact Recall</th>
                        <th>Fact Precision</th>
                        <th>Faithfulness</th>
                    </tr>
                </thead>
                <tbody>
                    $category_rows
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>Root-Cause Attribution</h2>
            <p class="subtitle">Of the <strong>failed</strong> gold facts, the split between a <em>retrieval gap</em> (no retrieved doc substantiated the fact) and a <em>generation gap</em> (evidence was retrieved but unused). N/A = no per-fact evidence.</p>
            <table>
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Model</th>
                        <th>Retrieval-Gap</th>
                        <th>Generation-Gap</th>
                        <th>Retrieval-Gap %</th>
                    </tr>
                </thead>
                <tbody>
                    $root_cause_rows
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""
    )
    return template.substitute(
        cat_k=k,
        summary_rows=html_summary_rows,
        cost_rows=html_cost_rows,
        category_rows=html_cat_rows,
        root_cause_rows=html_root_cause_rows,
    )


def render_report(jsonl_path: Path | str, output_dir: Path | str) -> tuple[Path, Path]:
    """Load evaluation JSONL, aggregate metrics, and write HTML/Markdown reports (FR-7)."""
    jsonl_path = Path(jsonl_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = generate_report_data(jsonl_path)

    md_content = render_markdown(data)
    html_content = render_html(data)

    md_path = output_dir / f"{jsonl_path.stem}.md"
    html_path = output_dir / f"{jsonl_path.stem}.html"

    md_path.write_text(md_content, encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")

    return html_path, md_path

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from enterprise_rag_ops.dashboard.data import (
    category_failure_distribution,
    cost_rows,
    discover_results_paths,
    failure_mode_distribution,
    format_cost,
    load_run_records,
    phoenix_trace_url,
    summary_rows,
)
from enterprise_rag_ops.eval.failure_taxonomy import FailureMode


def render(paths: list[Path]) -> None:
    """Render the dashboard UI for the selected result files (FR-2..5, FR-9..11)."""
    if not paths:
        st.warning("Please select at least one evaluation run.")
        return

    # Load concatenated records for pivots
    records = load_run_records(paths)
    if not records:
        st.info("No evaluation records found in the selected files.")
        return

    st.title("RAG Evaluation Dashboard")
    st.markdown(
        "Aggregate view of model quality, cost, and failure modes over the "
        "**EnterpriseRAG-Bench** dataset. Per-trace drill-down lives in Arize Phoenix."
    )

    # Tabs
    tab_summary, tab_failure, tab_cost, tab_category = st.tabs(
        ["📈 Summary", "🔍 Failure-mode", "💵 Cost", "📁 Category"]
    )

    # 1. Summary Tab (FR-2)
    with tab_summary:
        st.subheader("Model Quality Summary")
        st.markdown(
            "Overall performance metrics per model across the evaluation runs. "
            "Metrics are sourced directly from the evaluation pipeline."
        )

        all_summary = []
        for p in paths:
            rows = summary_rows(p)
            for row in rows:
                row_copy = dict(row)
                if len(paths) > 1:
                    row_copy["run"] = p.name
                all_summary.append(row_copy)

        if all_summary:
            df_summary = pd.DataFrame(all_summary)
            cols = [
                "model",
                "fact_recall",
                "fact_precision",
                "faithfulness",
                "abstain_precision",
                "abstain_recall",
            ]
            if "run" in df_summary.columns:
                cols = ["run", *cols]
            df_summary = df_summary[cols]

            rename_map = {
                "run": "Run File",
                "model": "Model",
                "fact_recall": "Fact Recall",
                "fact_precision": "Fact Precision",
                "faithfulness": "Faithfulness",
                "abstain_precision": "Abstain Precision",
                "abstain_recall": "Abstain Recall",
            }
            df_summary = df_summary.rename(columns=rename_map)

            st.dataframe(
                df_summary.style.format(
                    {
                        "Fact Recall": lambda x: f"{x * 100:.1f}%" if pd.notna(x) else "N/A",
                        "Fact Precision": lambda x: f"{x * 100:.1f}%" if pd.notna(x) else "N/A",
                        "Faithfulness": lambda x: f"{x * 100:.1f}%" if pd.notna(x) else "N/A",
                        "Abstain Precision": lambda x: f"{x * 100:.1f}%" if pd.notna(x) else "N/A",
                        "Abstain Recall": lambda x: f"{x * 100:.1f}%" if pd.notna(x) else "N/A",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No summary data available.")

    # 2. Failure-mode Tab (FR-3, FR-11)
    with tab_failure:
        st.subheader("Failure Mode Distribution")
        st.markdown(
            "Distribution of classified failure modes per model. "
            "The priority cascade classifies queries into correct, or one of 4 failure types."
        )

        dist = failure_mode_distribution(records)
        if dist:
            rows = []
            for model, fm_counts in dist.items():
                for fm_val, count in fm_counts.items():
                    rows.append({"Model": model, "Failure Mode": fm_val, "Count": count})
            df_fm = pd.DataFrame(rows)

            if not df_fm.empty:
                # Grouped bar chart
                chart = (
                    alt.Chart(df_fm)
                    .mark_bar()
                    .encode(
                        x=alt.X("Failure Mode:N", title="Failure Mode"),
                        y=alt.Y("Count:Q", title="Query Count"),
                        color=alt.Color("Model:N", title="Model"),
                        xOffset="Model:N",
                    )
                    .properties(height=350)
                    .interactive()
                )

                st.altair_chart(chart, use_container_width=True)

                # Pivot raw count table
                df_fm_pivot = (
                    df_fm.pivot(index="Model", columns="Failure Mode", values="Count")
                    .fillna(0)
                    .astype(int)
                )
                st.dataframe(df_fm_pivot, use_container_width=True)
            else:
                st.info("No failure mode counts available.")
        else:
            st.info("No failure mode data available.")

        # Phoenix Deep Links
        st.markdown("---")
        st.subheader("Failed Questions Details")
        st.markdown(
            "Detailed view of queries that did not pass evaluation. "
            "If Phoenix is running, deep-links are provided below to trace execution."
        )

        failed_rows = []
        for r in records:
            if r.failure_mode is not None and r.failure_mode != FailureMode.CORRECT.value:
                trace_url = phoenix_trace_url(r.question_id)
                row = {
                    "Question ID": r.question_id,
                    "Category": r.category,
                    "Model": r.gen_ai.request.model,
                    "Failure Mode": r.failure_mode,
                    "Fact Recall": r.fact_recall,
                    "Fact Precision": r.fact_precision,
                    "Faithfulness": r.faithfulness_ratio,
                }
                if trace_url is not None:
                    row["Phoenix Link"] = trace_url
                failed_rows.append(row)

        if failed_rows:
            df_failed = pd.DataFrame(failed_rows)
            column_config = {
                "Fact Recall": st.column_config.NumberColumn(format="%.1f%%"),
                "Fact Precision": st.column_config.NumberColumn(format="%.1f%%"),
                "Faithfulness": st.column_config.NumberColumn(format="%.1f%%"),
            }
            # Multiply percentage columns by 100 to display properly in NumberColumn with %
            for col in ["Fact Recall", "Fact Precision", "Faithfulness"]:
                df_failed[col] = df_failed[col].apply(lambda x: x * 100 if pd.notna(x) else None)

            if "Phoenix Link" in df_failed.columns:
                column_config["Phoenix Link"] = st.column_config.LinkColumn(
                    "Phoenix Link",
                    help="Deep-link to Arize Phoenix trace",
                    validate="^http",
                    max_chars=1000,
                    display_text="View Trace",
                )

            st.dataframe(
                df_failed, column_config=column_config, use_container_width=True, hide_index=True
            )
        else:
            st.success("🎉 All queries parsed correctly! Zero failures detected.")

    # 3. Cost Tab (FR-4)
    with tab_cost:
        st.subheader("Cost & Latency Rollup")
        st.markdown(
            "Aggregated API costs, generation latency, and token consumption per model. "
            "USD costs are computed based on token pricing configurations."
        )

        all_costs = []
        for p in paths:
            rows = cost_rows(p)
            for row in rows:
                row_copy = dict(row)
                if len(paths) > 1:
                    row_copy["run"] = p.name
                all_costs.append(row_copy)

        if all_costs:
            df_costs = pd.DataFrame(all_costs)
            cols = ["model", "total_cost", "mean_latency", "total_tokens"]
            if "run" in df_costs.columns:
                cols = ["run", *cols]
            df_costs = df_costs[cols]

            rename_map = {
                "run": "Run File",
                "model": "Model",
                "total_cost": "Total Cost",
                "mean_latency": "Mean Latency",
                "total_tokens": "Total Tokens",
            }
            df_costs = df_costs.rename(columns=rename_map)

            st.dataframe(
                df_costs.style.format(
                    {
                        "Total Cost": lambda x: format_cost(x) if pd.notna(x) else "N/A",
                        "Mean Latency": lambda x: f"{x:.2f}s" if pd.notna(x) else "N/A",
                        "Total Tokens": lambda x: f"{int(x):,}" if pd.notna(x) else "N/A",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No cost data available.")

    # 4. Category Tab (FR-9)
    with tab_category:
        st.subheader("Failure Modes by Category")
        st.markdown(
            "Breakdown of failure modes across the different benchmark question categories. "
            "Helps pinpoint which specific topics or formats trigger specific issues."
        )

        cat_dist = category_failure_distribution(records)
        if cat_dist:
            cat_rows = []
            for cat, fm_counts in cat_dist.items():
                for fm_val, count in fm_counts.items():
                    cat_rows.append({"Category": cat, "Failure Mode": fm_val, "Count": count})
            df_cat = pd.DataFrame(cat_rows)

            if not df_cat.empty:
                chart_cat = (
                    alt.Chart(df_cat)
                    .mark_bar()
                    .encode(
                        x=alt.X("Failure Mode:N", title="Failure Mode"),
                        y=alt.Y("Count:Q", title="Query Count"),
                        color=alt.Color("Category:N", title="Category"),
                        xOffset="Category:N",
                    )
                    .properties(height=350)
                    .interactive()
                )

                st.altair_chart(chart_cat, use_container_width=True)

                # Pivot raw table
                df_cat_pivot = (
                    df_cat.pivot(index="Category", columns="Failure Mode", values="Count")
                    .fillna(0)
                    .astype(int)
                )
                st.dataframe(df_cat_pivot, use_container_width=True)
            else:
                st.info("No failure mode counts by category available.")
        else:
            st.info("No failure mode category data available.")


def main() -> None:
    """App main entry point discovering results and calling render()."""
    # Page config for high-quality professional layout
    st.set_page_config(
        page_title="RAG Evaluation Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Discover paths
    paths = discover_results_paths()

    # Sidebar for run selection
    if not paths:
        st.warning("No evaluation results (*.jsonl) found in the `results/` directory.")
        return

    st.sidebar.title("Configuration")
    if len(paths) > 1:
        st.sidebar.markdown("### Select Runs to Load")
        selected_paths = st.sidebar.multiselect(
            "Evaluation Runs", options=paths, default=paths, format_func=lambda p: p.name
        )
    else:
        selected_paths = paths
        st.sidebar.info(f"Loaded single run: `{paths[0].name}`")

    render(selected_paths)


if __name__ == "__main__":
    main()

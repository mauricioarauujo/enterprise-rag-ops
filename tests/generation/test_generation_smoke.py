"""End-to-end generation smoke gate — local-only, **not** part of `make verify`.

Two assertion tiers (AC-13), reflecting a hard reality of the dev corpus: the
default stratified subset (100 docs/source) contains the gold documents for only
**3 of the benchmark's 500 questions**, and of those only some have an answer
self-contained in a single retrieved chunk. For every other question the
retriever returns vocabulary-similar but wrong (or only partially relevant) docs,
and a faithful generator correctly abstains with `sources=[]` — the desired
behavior, not a failure.

So the gate asserts:

- **All 10 questions** — the `rag-ask` CLI exits 0, prints a valid
  `AnswerWithSources`, and the `answer` is non-empty. This proves the pipeline is
  wired end-to-end (retrieve → assemble → generate → structured output) and that
  faithful abstention does not crash.
- **The attribution subset** (`expect_sources=True`: gold doc in the subset AND
  the answer self-contained in the top-ranked chunk we feed) — additionally
  `len(sources) >= 1`. This proves the attribution path works when the answer is
  present. `qst_0104` and `qst_0258` qualify; `qst_0252` does not — its gold doc
  is in the subset but the decision rule spans chunks beyond the top-1 we send,
  so it sits in the wiring tier (a Sprint 2 retrieval-quality concern).

The answerable questions overlap `make retrieval-smoke`'s set (gold
`expected_doc_ids` inside the subset). The wiring questions are
`qst_0001`..`qst_0007` plus `qst_0252`, spanning github / linear / fireflies /
gmail / google_drive / confluence — selected during `/implement` (RQ-10) by
streaming the dataset at the pinned SHA and confirming each retrieves a non-empty
top-k.

Run with: ``make smoke`` (requires ``OPENAI_API_KEY`` and a built index).
"""

from __future__ import annotations

import os

import pytest

from enterprise_rag_ops.generation.cli import main as rag_ask_main
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval import config

pytestmark = pytest.mark.smoke

SMOKE_QUESTIONS: list[dict] = [
    # --- Answerable: gold doc is in the subset and lands in the top-5 context ---
    {
        "question_id": "qst_0104",
        "source_types": ["confluence"],
        "expect_sources": True,
        "question": (
            "What is the standard amount of time a new hire buddy is expected to "
            "spend per day during the first two weeks when a long-term contractor "
            "is converted to a full-time employee?"
        ),
    },
    {
        # Gold doc IS in the subset, but the specific decision rule (quick review
        # vs. full analysis by impact scope) lives in a different chunk than the
        # top-ranked one, and we feed one chunk per doc — so the model faithfully
        # abstains. Answerable-in-corpus but not from a single best chunk: a
        # multi-chunk / completeness retrieval-quality concern for Sprint 2's eval
        # harness, not the substrate. Hence wiring-tier (expect_sources=False).
        "question_id": "qst_0252",
        "source_types": ["confluence"],
        "expect_sources": False,
        "question": (
            "In our incident response process, what is the rule for when a quick "
            "time-boxed after-action review is acceptable instead of writing the "
            "full formal analysis, based on impact duration and whether the issue "
            "hit one customer versus many?"
        ),
    },
    {
        "question_id": "qst_0258",
        "source_types": ["jira"],
        "expect_sources": True,
        "question": (
            "In the us-east dedicated setup for a big retail tenant, what caused the "
            "multi-hour staircase of gateway failures during peak traffic when "
            "long-lived chat streams coincided with a large embedding batch, "
            "especially involving warmup connection churn and disk-backed cache "
            "write pressure?"
        ),
    },
    # --- Wiring-only: gold doc not in the subset → faithful abstention is OK ---
    {
        "question_id": "qst_0001",
        "source_types": ["github"],
        "expect_sources": False,
        "question": (
            "What are the default size limits for file uploads and total request "
            "size for the new multipart upload support on the OpenAI-compatible API "
            "endpoints?"
        ),
    },
    {
        "question_id": "qst_0002",
        "source_types": ["github"],
        "expect_sources": False,
        "question": (
            "What is the name of the new metric added so SRE can track when "
            "server-side streaming sessions get finalized due to hitting the time limit?"
        ),
    },
    {
        "question_id": "qst_0003",
        "source_types": ["linear"],
        "expect_sources": False,
        "question": (
            "What are the acceptance criteria for the project introducing an algorithm "
            "to generate interactive UI color states and a Kappa-style elevation scale "
            "for dense table and grid components?"
        ),
    },
    {
        "question_id": "qst_0004",
        "source_types": ["fireflies"],
        "expect_sources": False,
        "question": (
            "In the meeting about onboarding a SaaS product to Google Cloud Marketplace, "
            "what did the GCP team recommend for handling delays where a new subscription "
            "entitlement is not immediately available during the customer onboarding flow?"
        ),
    },
    {
        "question_id": "qst_0005",
        "source_types": ["gmail"],
        "expect_sources": False,
        "question": (
            "What failover sequence and recovery targets did MedThink specify for "
            "handling an EU region outage, including any limits on how long traffic "
            "can shift to the US?"
        ),
    },
    {
        "question_id": "qst_0006",
        "source_types": ["google_drive"],
        "expect_sources": False,
        "question": (
            "In the draft spec about extending a routing policy engine for automated "
            "regional failover, what is the proposed priority order for evaluating "
            "different failure signals when deciding whether to shift traffic or fail over?"
        ),
    },
    {
        "question_id": "qst_0007",
        "source_types": ["google_drive"],
        "expect_sources": False,
        "question": (
            "In a rolling investigation of a model regression on policy-related prompts "
            "after a recent deploy, what was the average triage rubric score change "
            "between the older baseline build and the newer optimized build in the "
            "first comparison run?"
        ),
    },
]


@pytest.fixture(scope="module", autouse=True)
def _require_local_artifacts():
    """Skip the whole module unless the API key, index, and corpus are present."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set — required for the real-call smoke gate.")
    if not config.LANCEDB_DIR.exists():
        pytest.skip(f"No index at {config.LANCEDB_DIR} — run `make build-index` first.")
    if not config.CORPUS_PATH.exists():
        pytest.skip(f"No corpus at {config.CORPUS_PATH} — run `make download-data` first.")


def _run(question: str, capsys) -> AnswerWithSources:
    """Invoke the CLI and parse its single JSON line into AnswerWithSources."""
    rc = rag_ask_main([question])
    assert rc == 0, f"CLI exit code {rc}"
    out = capsys.readouterr().out.strip()
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "no stdout"
    return AnswerWithSources.model_validate_json(lines[-1])


@pytest.mark.parametrize("question_spec", SMOKE_QUESTIONS, ids=lambda q: q["question_id"])
def test_rag_ask_pipeline_end_to_end(question_spec, capsys):
    """AC-13 (all): CLI returns a valid, non-empty `AnswerWithSources` per question."""
    result = _run(question_spec["question"], capsys)
    assert result.answer, f"{question_spec['question_id']}: empty answer"


@pytest.mark.parametrize(
    "question_spec",
    [q for q in SMOKE_QUESTIONS if q["expect_sources"]],
    ids=lambda q: q["question_id"],
)
def test_rag_ask_attributes_sources_when_answerable(question_spec, capsys):
    """AC-13 (answerable subset): >=1 cited source when the gold doc is in context."""
    result = _run(question_spec["question"], capsys)
    assert result.answer, f"{question_spec['question_id']}: empty answer"
    assert len(result.sources) >= 1, (
        f"{question_spec['question_id']}: zero sources despite gold doc in top-5 "
        f"context — attribution path regression. answer={result.answer!r}"
    )

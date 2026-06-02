import json
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest

from enterprise_rag_ops.observability.exporter import replay_jsonl


class FakeSpanContext:
    def __init__(self, span_id: int):
        self._span_id = span_id

    @property
    def span_id(self) -> int:
        return self._span_id


class FakeSpan:
    def __init__(
        self, span_id: int, name: str, openinference_span_kind: str, attributes: dict[str, Any]
    ):
        self.span_id_int = span_id
        self.name = name
        self.openinference_span_kind = openinference_span_kind
        self.attributes = attributes
        self.parent_id = None

    def get_span_context(self) -> FakeSpanContext:
        return FakeSpanContext(self.span_id_int)


class FakeScoreSink:
    """In-memory mock implementation of ScoreSink (NFR-1)."""

    def __init__(self):
        self.projects_reset = []
        self.spans = []  # list of FakeSpan
        self.logged_scores = []
        self.flushed_count = 0
        self.current_span_id = 1
        self.span_stack = []

    def reset_project(self, project: str) -> None:
        self.projects_reset.append(project)

    @contextmanager
    def start_span(
        self, name: str, openinference_span_kind: str, attributes: dict[str, Any]
    ) -> Generator[FakeSpan, None, None]:
        span_id = self.current_span_id
        self.current_span_id += 1
        parent_id = self.span_stack[-1].span_id_int if self.span_stack else None

        span = FakeSpan(span_id, name, openinference_span_kind, attributes)
        span.parent_id = parent_id
        self.spans.append(span)

        self.span_stack.append(span)
        try:
            yield span
        finally:
            self.span_stack.pop()

    def log_scores(self, rows_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        self.logged_scores.append(rows_by_metric)

    def flush(self) -> None:
        self.flushed_count += 1


@pytest.fixture
def two_record_jsonl_content() -> str:
    """Return a 2-record JSONL content payload with various metric and cost configurations."""
    record1 = {
        "question_id": "qst_0001",
        "category": "basic",
        "run_id": "baseline",
        "k": 10,
        "gen_ai": {
            "request": {"model": "gpt-5-nano-2025-08-07"},
            "system": "openai",
            "operation": {"name": "chat"},
        },
        "generation": {
            "input_tokens": 100,
            "output_tokens": 200,
            "latency_s": 1.5,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.0001,
        },
        "judge": {
            "input_tokens": 300,
            "output_tokens": 400,
            "latency_s": 2.5,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.0002,
        },
        "answer": "Answer 1",
        "sources": ["doc_1"],
        "fact_recall": 1.0,
        "fact_precision": 0.8,
        "faithfulness_ratio": 0.9,
        "retrieval_ranked_ids": ["doc_1", "doc_2"],
        "did_abstain_retrieval": False,
        "did_abstain_e2e": False,
    }

    record2 = {
        "question_id": "qst_0002",
        "category": "complex",
        "run_id": "baseline",
        "k": 10,
        "gen_ai": {
            "request": {"model": "gpt-5-nano-2025-08-07"},
            "system": "openai",
            "operation": {"name": "chat"},
        },
        "generation": {
            "input_tokens": 120,
            "output_tokens": 250,
            "latency_s": 2.0,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": None,  # Test Q3 cost_usd None rule
        },
        "judge": {
            "input_tokens": 310,
            "output_tokens": 420,
            "latency_s": 3.0,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.0003,
        },
        "answer": "I abstain.",
        "sources": [],
        "fact_recall": None,  # Test None float skipped score row
        "fact_precision": 0.5,
        "faithfulness_ratio": None,  # Test None float skipped score row
        "retrieval_ranked_ids": [],
        "did_abstain_retrieval": True,
        "did_abstain_e2e": True,
    }
    return json.dumps(record1) + "\n" + json.dumps(record2) + "\n"


def test_exporter_offline_replay(tmp_path, two_record_jsonl_content):
    # Setup files
    jsonl_file = tmp_path / "test_baseline.jsonl"
    jsonl_file.write_text(two_record_jsonl_content)

    sink = FakeScoreSink()
    project_name = "test-project"

    # Run replay
    summary = replay_jsonl(jsonl_file, sink, project=project_name, dry_run=False)

    # Assert parsed/exported counts
    assert summary.records_parsed == 2
    assert summary.traces_exported == 2
    # Record 1: 5 scores logged. Record 2: did_abstain_e2e, did_abstain_retrieval, fact_precision. (Total 8)
    assert summary.scores_logged == 8

    # (a) Verify span tree shape and parent/child nesting
    assert len(sink.spans) == 8
    # Spans are stored chronologically
    # Tree 1: spans 0 to 3
    # Tree 2: spans 4 to 7
    chain1 = sink.spans[0]
    retriever1 = sink.spans[1]
    gen1 = sink.spans[2]
    judge1 = sink.spans[3]

    assert chain1.name == "qst_0001"
    assert chain1.openinference_span_kind == "chain"
    assert chain1.parent_id is None

    for child in [retriever1, gen1, judge1]:
        assert child.parent_id == chain1.span_id_int
        assert child.parent_id is not None

    assert retriever1.openinference_span_kind == "retriever"
    assert gen1.openinference_span_kind == "llm"
    assert judge1.openinference_span_kind == "llm"

    # (b) Verify attributes on each span (per ADR-0004)
    assert chain1.attributes["question_id"] == "qst_0001"
    assert chain1.attributes["category"] == "basic"
    assert chain1.attributes["run_id"] == "baseline"
    assert chain1.attributes["k"] == 10
    assert chain1.attributes["gen_ai.request.model"] == "gpt-5-nano-2025-08-07"
    assert chain1.attributes["gen_ai.system"] == "openai"
    assert chain1.attributes["gen_ai.operation.name"] == "chat"

    # Retriever span rank + document id attributes flattening
    assert retriever1.attributes["retrieval.documents.0.document.id"] == "doc_1"
    assert retriever1.attributes["retrieval.documents.0.document.rank"] == 0
    assert retriever1.attributes["retrieval.documents.1.document.id"] == "doc_2"
    assert retriever1.attributes["retrieval.documents.1.document.rank"] == 1
    # Check that document content/score attributes are NOT present
    assert "retrieval.documents.0.document.content" not in retriever1.attributes
    assert "retrieval.documents.0.document.score" not in retriever1.attributes

    # LLM spans usage, latency, model attributes
    assert gen1.attributes["gen_ai.request.model"] == "gpt-5-nano-2025-08-07"
    assert gen1.attributes["gen_ai.system"] == "openai"
    assert gen1.attributes["gen_ai.usage.input_tokens"] == 100
    assert gen1.attributes["gen_ai.usage.output_tokens"] == 200
    assert gen1.attributes["latency_s"] == 1.5

    # (d) Verify cost attributes (Q3 cost_usd None rule)
    assert gen1.attributes["cost_usd"] == 0.0001
    assert judge1.attributes["cost_usd"] == 0.0002
    assert chain1.attributes["cost_usd_total"] == pytest.approx(0.0003)  # Both known

    # Verify Record 2 cost details (one is None)
    chain2 = sink.spans[4]
    gen2 = sink.spans[6]
    judge2 = sink.spans[7]

    assert "cost_usd" not in gen2.attributes  # Omitted because it was None
    assert judge2.attributes["cost_usd"] == 0.0003
    assert "cost_usd_total" not in chain2.attributes  # Omitted because one of them was None

    # (c, e) Verify scores attachment, labels, and skipped None floats
    assert len(sink.logged_scores) == 1
    scores_dict = sink.logged_scores[0]

    # did_abstain_e2e (BOOLEAN) -> attached to chain
    assert len(scores_dict["did_abstain_e2e"]) == 2
    assert scores_dict["did_abstain_e2e"][0]["span_id"] == f"{chain1.span_id_int:016x}"
    assert scores_dict["did_abstain_e2e"][0]["score"] == 0.0
    assert scores_dict["did_abstain_e2e"][0]["label"] == "false"
    assert scores_dict["did_abstain_e2e"][1]["span_id"] == f"{chain2.span_id_int:016x}"
    assert scores_dict["did_abstain_e2e"][1]["score"] == 1.0
    assert scores_dict["did_abstain_e2e"][1]["label"] == "true"

    # did_abstain_retrieval (BOOLEAN) -> attached to retriever
    assert len(scores_dict["did_abstain_retrieval"]) == 2
    assert scores_dict["did_abstain_retrieval"][0]["span_id"] == f"{retriever1.span_id_int:016x}"
    assert scores_dict["did_abstain_retrieval"][1]["score"] == 1.0
    assert scores_dict["did_abstain_retrieval"][1]["label"] == "true"

    # faithfulness_ratio (NUMERIC) -> attached to generation. Record 2 is None, so it must be SKIPPED (e)
    assert len(scores_dict["faithfulness_ratio"]) == 1
    assert scores_dict["faithfulness_ratio"][0]["span_id"] == f"{gen1.span_id_int:016x}"
    assert scores_dict["faithfulness_ratio"][0]["score"] == 0.9

    # fact_recall (NUMERIC) -> judge. Record 2 is None, skipped (e)
    assert len(scores_dict["fact_recall"]) == 1
    assert scores_dict["fact_recall"][0]["span_id"] == f"{judge1.span_id_int:016x}"
    assert scores_dict["fact_recall"][0]["score"] == 1.0

    # fact_precision (NUMERIC) -> judge. Both known
    assert len(scores_dict["fact_precision"]) == 2
    assert scores_dict["fact_precision"][0]["span_id"] == f"{judge1.span_id_int:016x}"
    assert scores_dict["fact_precision"][0]["score"] == 0.8
    assert scores_dict["fact_precision"][1]["span_id"] == f"{sink.spans[7].span_id_int:016x}"
    assert scores_dict["fact_precision"][1]["score"] == 0.5

    # (f) Verify reset-and-replay idempotency
    assert sink.projects_reset == [project_name]
    assert sink.flushed_count == 2  # one after traces, one after scores

    # A second replay_jsonl run on the same project
    replay_jsonl(jsonl_file, sink, project=project_name, dry_run=False)
    assert sink.projects_reset == [project_name, project_name]  # Reset called again


def test_exporter_dry_run(tmp_path, two_record_jsonl_content):
    jsonl_file = tmp_path / "test_baseline.jsonl"
    jsonl_file.write_text(two_record_jsonl_content)

    sink = FakeScoreSink()
    summary = replay_jsonl(jsonl_file, sink, project="test-project", dry_run=True)

    # Dry-run validation (FR-11, AC-13)
    assert summary.records_parsed == 2
    assert summary.traces_exported == 0
    assert summary.scores_logged == 0
    assert len(sink.spans) == 0
    assert len(sink.projects_reset) == 0
    assert len(sink.logged_scores) == 0


def test_cli_endpoint_precedence(tmp_path, two_record_jsonl_content):
    from unittest.mock import patch

    from enterprise_rag_ops.observability import cli

    jsonl_file = tmp_path / "test_baseline.jsonl"
    jsonl_file.write_text(two_record_jsonl_content)

    # Precedence case 1: Flag overrides everything
    with (
        patch("enterprise_rag_ops.observability.cli.PhoenixScoreSink") as mock_sink_cls,
        patch("enterprise_rag_ops.observability.cli.replay_jsonl"),
    ):
        cli.main(
            [
                "--results",
                str(jsonl_file),
                "--endpoint",
                "http://flag-endpoint:1234",
                "--project",
                "test-project",
            ]
        )
        mock_sink_cls.assert_called_once_with(
            project="test-project", endpoint="http://flag-endpoint:1234"
        )

    # Precedence case 2: Env var fallback
    with (
        patch("enterprise_rag_ops.observability.cli.PhoenixScoreSink") as mock_sink_cls,
        patch("enterprise_rag_ops.observability.cli.replay_jsonl"),
        patch.dict("os.environ", {"PHOENIX_COLLECTOR_ENDPOINT": "http://env-endpoint:5678"}),
    ):
        # Ensure we don't have conflicting args
        cli.main(["--results", str(jsonl_file), "--project", "test-project"])
        mock_sink_cls.assert_called_once_with(
            project="test-project", endpoint="http://env-endpoint:5678"
        )

    # Precedence case 3: Default fallback
    with (
        patch("enterprise_rag_ops.observability.cli.PhoenixScoreSink") as mock_sink_cls,
        patch("enterprise_rag_ops.observability.cli.replay_jsonl"),
        patch.dict("os.environ", {}, clear=True),
    ):
        cli.main(["--results", str(jsonl_file), "--project", "test-project"])
        mock_sink_cls.assert_called_once_with(
            project="test-project", endpoint="http://localhost:6006"
        )


def test_split_endpoint_normalizes_otlp_and_base_url():
    """Regression: live exit demo hit 405 because `register(endpoint=...)` was passed
    a bare host (`http://localhost:6006`) instead of the full OTLP-HTTP traces URL.
    Lock the helper that splits user input into the two distinct URLs Phoenix needs."""
    from enterprise_rag_ops.observability.phoenix_client import split_endpoint

    # Bare host (the CLI default): must append /v1/traces for OTLP, leave base as-is.
    assert split_endpoint("http://localhost:6006") == (
        "http://localhost:6006/v1/traces",
        "http://localhost:6006",
    )
    # Trailing slash is tolerated and normalized.
    assert split_endpoint("http://localhost:6006/") == (
        "http://localhost:6006/v1/traces",
        "http://localhost:6006",
    )
    # User already supplied the OTLP path: keep it for register, strip for client.
    assert split_endpoint("http://localhost:6006/v1/traces") == (
        "http://localhost:6006/v1/traces",
        "http://localhost:6006",
    )
    # Non-default host + port survives both sides.
    assert split_endpoint("https://phoenix.example.com:443") == (
        "https://phoenix.example.com:443/v1/traces",
        "https://phoenix.example.com:443",
    )


def test_cli_dry_run(tmp_path, two_record_jsonl_content):
    from unittest.mock import patch

    from enterprise_rag_ops.observability import cli

    jsonl_file = tmp_path / "test_baseline.jsonl"
    jsonl_file.write_text(two_record_jsonl_content)

    # Verify dry-run doesn't call PhoenixScoreSink
    with (
        patch("enterprise_rag_ops.observability.cli.PhoenixScoreSink") as mock_sink_cls,
        patch("enterprise_rag_ops.observability.cli.replay_jsonl") as mock_replay,
    ):
        cli.main(["--results", str(jsonl_file), "--dry-run", "--project", "test-project"])
        mock_sink_cls.assert_not_called()
        mock_replay.assert_called_once()
        # Verify it passed a NoOpScoreSink subclass instance
        called_sink = mock_replay.call_args[1]["sink"]
        assert isinstance(called_sink, cli.NoOpScoreSink)


# --- Phase 16: --enrich-from-index content hydration -----------------------------------


def _one_record_jsonl(ranked_ids: list[str]) -> str:
    """A single valid EvalRecord JSONL line with the given doc-level ranked ids."""
    rec = {
        "question_id": "qst_0001",
        "category": "basic",
        "run_id": "baseline",
        "k": 10,
        "gen_ai": {
            "request": {"model": "gpt-5-nano-2025-08-07"},
            "system": "openai",
            "operation": {"name": "chat"},
        },
        "generation": {
            "input_tokens": 100,
            "output_tokens": 200,
            "latency_s": 1.5,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.0001,
        },
        "judge": {
            "input_tokens": 300,
            "output_tokens": 400,
            "latency_s": 2.5,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.0002,
        },
        "answer": "Answer 1",
        "sources": list(ranked_ids),
        "fact_recall": 1.0,
        "fact_precision": 0.8,
        "faithfulness_ratio": 0.9,
        "retrieval_ranked_ids": list(ranked_ids),
        "did_abstain_retrieval": False,
        "did_abstain_e2e": False,
    }
    return json.dumps(rec) + "\n"


def _retriever_attrs(sink: "FakeScoreSink") -> dict[str, Any]:
    return next(s.attributes for s in sink.spans if s.openinference_span_kind == "retriever")


def test_ac1_enrich_default_no_behavior_change(tmp_path):
    """AC-1: no doc_lookup -> only .id/.rank, no .content (byte-identical to today)."""
    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(_one_record_jsonl(["d1", "d2"]))
    sink = FakeScoreSink()

    replay_jsonl(jsonl, sink, project="p")  # default doc_lookup=None

    attrs = _retriever_attrs(sink)
    assert attrs["retrieval.documents.0.document.id"] == "d1"
    assert attrs["retrieval.documents.0.document.rank"] == 0
    assert "retrieval.documents.0.document.content" not in attrs
    assert "retrieval.documents.1.document.content" not in attrs


def test_ac2_content_hydration_with_fake_lookup(tmp_path):
    """AC-2: doc_lookup hydrates .content per doc; .id/.rank preserved; no file I/O."""
    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(_one_record_jsonl(["d1", "d2"]))
    sink = FakeScoreSink()

    replay_jsonl(jsonl, sink, project="p", doc_lookup={"d1": "alpha text", "d2": "beta text"})

    attrs = _retriever_attrs(sink)
    assert attrs["retrieval.documents.0.document.content"] == "alpha text"
    assert attrs["retrieval.documents.1.document.content"] == "beta text"
    assert attrs["retrieval.documents.0.document.id"] == "d1"
    assert attrs["retrieval.documents.1.document.id"] == "d2"
    assert attrs["retrieval.documents.0.document.rank"] == 0
    assert attrs["retrieval.documents.1.document.rank"] == 1


def test_ac3_missing_doc_id_omit_and_warn(tmp_path, caplog):
    """AC-3: a ranked id absent from the map omits .content + warns; no crash."""
    import logging

    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(_one_record_jsonl(["d1", "dX"]))
    sink = FakeScoreSink()

    with caplog.at_level(logging.WARNING):
        replay_jsonl(jsonl, sink, project="p", doc_lookup={"d1": "alpha text"})

    attrs = _retriever_attrs(sink)
    assert attrs["retrieval.documents.0.document.content"] == "alpha text"
    assert "retrieval.documents.1.document.content" not in attrs
    assert "dX" in caplog.text


def test_ac4_no_score_key_in_v1(tmp_path):
    """AC-4: enrichment never writes a .document.score key."""
    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(_one_record_jsonl(["d1", "d2"]))
    sink = FakeScoreSink()

    replay_jsonl(jsonl, sink, project="p", doc_lookup={"d1": "a", "d2": "b"})

    attrs = _retriever_attrs(sink)
    assert not any(".document.score" in key for key in attrs)


def test_ac5_attributes_purity_and_unchanged_signature():
    """AC-5: build_span_attrs keeps its single-param signature; attributes.py imports no
    retrieval/ingest/phoenix/otel (scan import statements only, not comments)."""
    import inspect

    from enterprise_rag_ops.observability import attributes as attrs_mod

    assert list(inspect.signature(attrs_mod.build_span_attrs).parameters) == ["record"]

    import_lines = " ".join(
        ln.strip()
        for ln in inspect.getsource(attrs_mod).splitlines()
        if ln.strip().startswith(("import ", "from "))
    )
    for forbidden in ("retrieval", "ingest", "phoenix", "opentelemetry"):
        assert forbidden not in import_lines, f"attributes.py imports {forbidden}"


def test_ac6_offline_no_heavy_import(tmp_path):
    """AC-6: the enrichment path runs on a purely in-memory lookup + fake sink — content
    comes from the map, not a corpus file (none exists), and no real Phoenix/LanceDB sink
    is involved."""
    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(_one_record_jsonl(["d1"]))
    sink = FakeScoreSink()

    replay_jsonl(jsonl, sink, project="p", doc_lookup={"d1": "alpha"})

    # No corpus.jsonl was created or read — content came from the in-memory Mapping.
    assert not (tmp_path / "corpus.jsonl").exists()
    assert _retriever_attrs(sink)["retrieval.documents.0.document.content"] == "alpha"


def test_ac7_cli_wires_corpus_map_only_with_flag(tmp_path, two_record_jsonl_content):
    """AC-7: --enrich-from-index builds the map once via read_corpus and passes it;
    without the flag, read_corpus is never called and doc_lookup is None."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from enterprise_rag_ops.observability import cli

    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(two_record_jsonl_content)
    fake_docs = [
        SimpleNamespace(id="doc_1", text="alpha"),
        SimpleNamespace(id="doc_2", text="beta"),
    ]

    with (
        patch(
            "enterprise_rag_ops.observability.cli.read_corpus", return_value=iter(fake_docs)
        ) as mock_rc,
        patch("enterprise_rag_ops.observability.cli.replay_jsonl") as mock_replay,
        patch("enterprise_rag_ops.observability.cli.PhoenixScoreSink"),
    ):
        cli.main(["--results", str(jsonl), "--project", "p", "--enrich-from-index"])
        mock_rc.assert_called_once()
        assert mock_replay.call_args[1]["doc_lookup"] == {"doc_1": "alpha", "doc_2": "beta"}

    with (
        patch("enterprise_rag_ops.observability.cli.read_corpus") as mock_rc2,
        patch("enterprise_rag_ops.observability.cli.replay_jsonl") as mock_replay2,
        patch("enterprise_rag_ops.observability.cli.PhoenixScoreSink"),
    ):
        cli.main(["--results", str(jsonl), "--project", "p"])
        mock_rc2.assert_not_called()
        assert mock_replay2.call_args[1]["doc_lookup"] is None


def test_ac7_help_lists_flag(capsys):
    """AC-7: rag-export-traces --help exits 0 and advertises --enrich-from-index."""
    from enterprise_rag_ops.observability import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    assert "--enrich-from-index" in capsys.readouterr().out


def test_ac8_map_from_corpus_drives_hydration(tmp_path):
    """AC-8: a {doc.id: doc.text} map built from a fake Document iterable drives AC-2
    hydration end-to-end through replay_jsonl."""
    from types import SimpleNamespace

    fake_docs = [SimpleNamespace(id="d1", text="alpha"), SimpleNamespace(id="d2", text="beta")]
    doc_lookup = {doc.id: doc.text for doc in fake_docs}

    jsonl = tmp_path / "b.jsonl"
    jsonl.write_text(_one_record_jsonl(["d1", "d2"]))
    sink = FakeScoreSink()

    replay_jsonl(jsonl, sink, project="p", doc_lookup=doc_lookup)

    attrs = _retriever_attrs(sink)
    assert attrs["retrieval.documents.0.document.content"] == "alpha"
    assert attrs["retrieval.documents.1.document.content"] == "beta"

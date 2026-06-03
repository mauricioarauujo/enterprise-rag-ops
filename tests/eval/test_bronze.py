"""Tests for BronzeWriter (AC-4, AC-5, AC-6) and provider serializers (AC-2)."""

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise_rag_ops.eval.bronze import BronzeWriter
from enterprise_rag_ops.eval.openai_judge import _serialize_response as judge_serialize
from enterprise_rag_ops.generation.anthropic_generator import (
    _serialize_response as anthropic_serialize,
)
from enterprise_rag_ops.generation.gemini_generator import _serialize_response as gemini_serialize
from enterprise_rag_ops.generation.openai_generator import _serialize_response as openai_serialize


def test_bronze_writer_key_scheme_and_idempotency(tmp_path: Path):
    """Assert key scheme data/raw_eval/{run_id}/{qid}__{model}__{call_type}.json and overwrite behavior."""
    writer = BronzeWriter(run_id="run1", root=tmp_path)

    payload1 = {"test": "data1"}
    file_path = writer.write("q1", "modelA", "gen", payload1)

    expected_path = tmp_path / "run1" / "q1__modelA__gen.json"
    assert file_path == expected_path
    assert file_path.exists()

    with open(file_path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == payload1

    # Idempotency / Overwrite
    payload2 = {"test": "data2", "other": "value"}
    file_path_2 = writer.write("q1", "modelA", "gen", payload2)
    assert file_path_2 == expected_path

    with open(file_path, encoding="utf-8") as f:
        loaded2 = json.load(f)
    assert loaded2 == payload2


def test_bronze_writer_sanitization(tmp_path: Path):
    """Assert run_id validation raises ValueError on illegal paths."""
    # Invalid run_ids
    for invalid_id in ["run/id", f"run{os.sep}id", "../outside", "..", "run/../id"]:
        with pytest.raises(ValueError):
            BronzeWriter(run_id=invalid_id, root=tmp_path)

    # Valid run_id
    writer = BronzeWriter(run_id="2026-06-03_10-00-00_baseline", root=tmp_path)
    assert writer.run_id == "2026-06-03_10-00-00_baseline"


def test_bronze_writer_thread_safety(tmp_path: Path):
    """Assert two threads writing concurrently write valid non-interleaved JSON files immediately."""
    writer = BronzeWriter(run_id="thread_run", root=tmp_path)

    num_writes = 50
    errors = []

    def worker_thread(thread_id: int):
        try:
            for i in range(num_writes):
                qid = f"t{thread_id}_q{i}"
                payload = {"thread": thread_id, "index": i, "timestamp": time.time()}
                path = writer.write(qid, "modelX", "gen", payload)
                # Confirm it is readable immediately
                with open(path, encoding="utf-8") as f:
                    content = json.load(f)
                assert content["thread"] == thread_id
                assert content["index"] == i
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker_thread, args=(1,))
    t2 = threading.Thread(target=worker_thread, args=(2,))

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    assert not errors, f"Errors in threads: {errors}"


def test_provider_response_serializers_defensive():
    """Assert serializers return JSON-able dicts and fallback safely on sparse/missing fields."""

    # 1. OpenAI serializer
    sparse_openai = SimpleNamespace(
        model="gpt-test",
        system_fingerprint="fp_123",
        choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="openai text"))
        ],
    )
    res_openai = openai_serialize(sparse_openai)
    assert res_openai["model"] == "gpt-test"
    assert res_openai["system_fingerprint"] == "fp_123"
    assert res_openai["choices"][0]["finish_reason"] == "stop"
    assert res_openai["choices"][0]["message"]["content"] == "openai text"
    assert "refusal" not in res_openai["choices"][0]["message"]
    # Check it serializes to JSON
    assert json.dumps(res_openai)

    # 2. Anthropic serializer
    sparse_anthropic = SimpleNamespace(
        model="claude-test",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="anthropic text")],
    )
    res_anthropic = anthropic_serialize(sparse_anthropic)
    assert res_anthropic["model"] == "claude-test"
    assert res_anthropic["stop_reason"] == "end_turn"
    assert res_anthropic["content"][0]["type"] == "text"
    assert res_anthropic["content"][0]["text"] == "anthropic text"
    assert json.dumps(res_anthropic)

    # 3. Gemini serializer
    sparse_gemini = SimpleNamespace(
        text="gemini text",
        model_version="v2.5",
        candidates=[
            SimpleNamespace(
                finish_reason="STOP",
                content=SimpleNamespace(role="model", parts=[SimpleNamespace(text="part text")]),
            )
        ],
    )
    res_gemini = gemini_serialize(sparse_gemini)
    assert res_gemini["text"] == "gemini text"
    assert res_gemini["model_version"] == "v2.5"
    assert res_gemini["candidates"][0]["finish_reason"] == "STOP"
    assert res_gemini["candidates"][0]["content"]["role"] == "model"
    assert res_gemini["candidates"][0]["content"]["parts"][0]["text"] == "part text"
    assert json.dumps(res_gemini)

    # 4. OpenAI Judge serializer (shares the same structure/logic as OpenAI generator)
    sparse_judge = SimpleNamespace(
        model="judge-model",
        choices=[
            SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="judge output"))
        ],
    )
    res_judge = judge_serialize(sparse_judge)
    assert res_judge["model"] == "judge-model"
    assert res_judge["choices"][0]["finish_reason"] == "length"
    assert res_judge["choices"][0]["message"]["content"] == "judge output"
    assert json.dumps(res_judge)

    # 5. Extremes: completely empty objects / non-existent fields must not raise
    empty_obj = SimpleNamespace()
    assert openai_serialize(empty_obj) == {}
    assert anthropic_serialize(empty_obj) == {}
    assert gemini_serialize(empty_obj) == {}
    assert judge_serialize(empty_obj) == {}

    # 6. Hard error (like an int or string response object) yields error dict instead of crashing
    bad_resp = 42
    assert "_serialization_error" in openai_serialize(bad_resp)
    assert "_serialization_error" in anthropic_serialize(bad_resp)
    assert "_serialization_error" in gemini_serialize(bad_resp)
    assert "_serialization_error" in judge_serialize(bad_resp)

"""Unit tests for GeminiGenerator (AC-1 to AC-5, AC-11)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.generation.gemini_generator import GeminiGenerator
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

# --- Fake client for offline testing (AC-2, AC-3) ---------------------------


class FakeUsageMetadata:
    def __init__(
        self,
        prompt_token_count: int | None = None,
        candidates_token_count: int | None = None,
        thoughts_token_count: int | None = None,
    ) -> None:
        if prompt_token_count is not None:
            self.prompt_token_count = prompt_token_count
        if candidates_token_count is not None:
            self.candidates_token_count = candidates_token_count
        if thoughts_token_count is not None:
            self.thoughts_token_count = thoughts_token_count


class FakeTokenCandidate:
    def __init__(self, log_probability: float | None = None, token: str | None = None) -> None:
        if log_probability is not None:
            self.log_probability = log_probability
        if token is not None:
            self.token = token


class FakeTopCandidatesEntry:
    def __init__(self, candidates: list[FakeTokenCandidate] | None = None) -> None:
        if candidates is not None:
            self.candidates = candidates


class FakeLogprobsResult:
    def __init__(self, top_candidates: list[FakeTopCandidatesEntry] | None = None) -> None:
        if top_candidates is not None:
            self.top_candidates = top_candidates


class FakeCandidate:
    def __init__(
        self,
        avg_logprobs: float | None = None,
        logprobs_result: FakeLogprobsResult | None = None,
    ) -> None:
        if avg_logprobs is not None:
            self.avg_logprobs = avg_logprobs
        if logprobs_result is not None:
            self.logprobs_result = logprobs_result


class FakeResponse:
    def __init__(
        self,
        text: str,
        usage_metadata: FakeUsageMetadata | None = None,
        candidates: list[FakeCandidate] | None = None,
    ) -> None:
        self.text = text
        self.usage_metadata = usage_metadata
        if candidates is not None:
            self.candidates = candidates


class FakeGeminiClient:
    def __init__(
        self,
        response_text: str,
        usage_metadata: FakeUsageMetadata | None = None,
        candidates: list[FakeCandidate] | None = None,
    ) -> None:
        self.response_text = response_text
        self.usage_metadata = usage_metadata
        self.candidates = candidates
        self.calls: list[dict] = []

        class Models:
            def generate_content(self_inner, model, contents, config):
                self.calls.append(
                    {
                        "model": model,
                        "contents": contents,
                        "config": config,
                    }
                )
                return FakeResponse(self.response_text, self.usage_metadata, self.candidates)

        self.models = Models()


# --- Unit Tests --------------------------------------------------------------


def test_offline_injected_client():
    """AC-2: GeminiGenerator parses answer and sources; extra fields raise ValidationError."""
    # Happy path
    happy_json = '{"answer": "Gemini generated answer.", "sources": ["doc_123"]}'
    fake_client = FakeGeminiClient(response_text=happy_json)
    generator = GeminiGenerator(model="gemini-test", client=fake_client)

    chunks = [Chunk(chunk_id="doc_123::0", doc_id="doc_123", text="Ref text")]
    import json

    from enterprise_rag_ops.eval.raw_call import RawCall

    result, stats, raw = generator.generate_with_stats(chunks, "Question?")

    assert result.answer == "Gemini generated answer."
    assert result.sources == ["doc_123"]
    assert stats.system == "google"
    assert stats.model == "gemini-test"
    assert stats.latency_s > 0.0

    assert isinstance(raw, RawCall)
    assert raw.request["model"] == "gemini-test"
    assert "contents" in raw.request
    assert json.dumps(raw.response)
    assert raw.response["text"] == happy_json

    # Ensure native JSON config was sent correctly (FR-2)
    assert len(fake_client.calls) == 1
    call_kwargs = fake_client.calls[0]
    config = call_kwargs["config"]
    assert config.response_mime_type == "application/json"
    # The schema handed to Gemini must be the OPEN mirror — Gemini's schema dialect
    # rejects the `additionalProperties` that AnswerWithSources(extra="forbid") emits
    # (regression guard for the live 400 "Unknown name additional_properties").
    assert "additionalProperties" not in config.response_schema.model_json_schema()
    # Field sets must match AnswerWithSources EXACTLY — machine-checks the open mirror
    # against the real schema in both directions, so a future field added to
    # AnswerWithSources fails here instead of silently in a live Gemini call.
    assert set(config.response_schema.model_fields) == set(AnswerWithSources.model_fields)

    # Extra field path
    extra_field_json = (
        '{"answer": "Gemini generated.", "sources": ["doc_123"], "extra_key": "forbid-me"}'
    )
    fake_client_extra = FakeGeminiClient(response_text=extra_field_json)
    generator_extra = GeminiGenerator(model="gemini-test", client=fake_client_extra)

    with pytest.raises(ValidationError):
        generator_extra.generate_with_stats(chunks, "Question?")


def test_token_mapping():
    """AC-3: verify token mapping (output = candidates + thoughts) and defensive getattr defaults."""
    chunks = [Chunk(chunk_id="doc_123::0", doc_id="doc_123", text="Ref text")]
    happy_json = '{"answer": "Gemini generated answer.", "sources": ["doc_123"]}'

    # Case 1: All values present
    usage = FakeUsageMetadata(
        prompt_token_count=10,
        candidates_token_count=20,
        thoughts_token_count=5,
    )
    fake_client = FakeGeminiClient(response_text=happy_json, usage_metadata=usage)
    generator = GeminiGenerator(client=fake_client)
    _, stats, _ = generator.generate_with_stats(chunks, "Q")
    assert stats.input_tokens == 10
    assert stats.output_tokens == 25

    # Case 2: thoughts_token_count missing / None
    usage_no_thoughts = FakeUsageMetadata(
        prompt_token_count=12,
        candidates_token_count=18,
        thoughts_token_count=None,
    )
    fake_client = FakeGeminiClient(response_text=happy_json, usage_metadata=usage_no_thoughts)
    generator = GeminiGenerator(client=fake_client)
    _, stats, _ = generator.generate_with_stats(chunks, "Q")
    assert stats.input_tokens == 12
    assert stats.output_tokens == 18

    # Case 3: usage_metadata missing completely (None)
    fake_client_no_usage = FakeGeminiClient(response_text=happy_json, usage_metadata=None)
    generator = GeminiGenerator(client=fake_client_no_usage)
    _, stats, _ = generator.generate_with_stats(chunks, "Q")
    assert stats.input_tokens == 0
    assert stats.output_tokens == 0

    # Case 4: usage_metadata exists but has no attributes (defensive getattr check)
    class EmptyUsageMetadata:
        pass

    fake_client_empty = FakeGeminiClient(
        response_text=happy_json, usage_metadata=EmptyUsageMetadata()
    )
    generator = GeminiGenerator(client=fake_client_empty)
    _, stats, _ = generator.generate_with_stats(chunks, "Q")
    assert stats.input_tokens == 0
    assert stats.output_tokens == 0


def test_env_guard(monkeypatch):
    """AC-4: constructor raises clean RuntimeError when both API keys are missing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set"):
        GeminiGenerator()

    # If either is set, it does not raise RuntimeError (though calling API without a key will fail, init passes)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    # Setting GEMINI_API_KEY allows constructor to complete (it'll try to call genai.Client(), which won't throw on dummy keys)
    # We catch any SDK init error or pass if it succeeds.
    try:
        GeminiGenerator()
    except RuntimeError:
        pytest.fail("GeminiGenerator raised RuntimeError even though GEMINI_API_KEY was set.")
    except Exception:
        # Other exceptions (like google-auth gcp metadata server warnings) are fine, the guard didn't block it.
        pass

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key")
    try:
        GeminiGenerator()
    except RuntimeError:
        pytest.fail("GeminiGenerator raised RuntimeError even though GOOGLE_API_KEY was set.")
    except Exception:
        pass


def test_model_resolution(monkeypatch):
    """AC-5: default model model precedence (explicit > env > default)."""
    fake_client = FakeGeminiClient(response_text='{"answer": "A", "sources": []}')

    # Default model
    monkeypatch.delenv("RAG_GEN_MODEL_GOOGLE", raising=False)
    generator_default = GeminiGenerator(client=fake_client)
    assert generator_default._model == "gemini-2.5-flash-lite"

    # Env var overrides
    monkeypatch.setenv("RAG_GEN_MODEL_GOOGLE", "gemini-env-override")
    generator_env = GeminiGenerator(client=fake_client)
    assert generator_env._model == "gemini-env-override"

    # Explicit wins
    generator_explicit = GeminiGenerator(model="explicit-gemini-model", client=fake_client)
    assert generator_explicit._model == "explicit-gemini-model"


# --- VCR cassette test (AC-1) ------------------------------------------------


@pytest.mark.vcr
@pytest.mark.skipif(
    os.environ.get("VCR_RECORD_MODE") != "once"
    and not (
        Path(__file__).parent.parent / "eval" / "cassettes" / "gemini_generator.yaml"
    ).exists(),
    reason="cassette not yet recorded — live step",
)
def test_live_replay(vcr_record, monkeypatch):
    """AC-1: Live call replayed offline via VCR cassette (no network, no key)."""
    # Ensure GEMINI_API_KEY is set to a dummy value so GeminiGenerator initializes
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-replay")

    generator = GeminiGenerator()
    chunks = [
        Chunk(
            chunk_id="test_doc::0",
            doc_id="test_doc",
            text="The default port for HTTP traffic is 80; for HTTPS it is 443.",
        )
    ]
    question = "What is the default port for HTTP traffic?"

    with vcr_record.use_cassette("gemini_generator.yaml"):
        result, stats, raw = generator.generate_with_stats(chunks, question)

    assert "80" in result.answer
    assert result.sources == ["test_doc"]
    assert stats.input_tokens > 0
    assert stats.output_tokens > 0
    assert stats.latency_s > 0.0
    assert stats.system == "google"
    assert stats.model == "gemini-2.5-flash-lite"
    assert raw.request["model"] == generator._model
    assert "contents" in raw.request
    assert "text" in raw.response


def test_offline_confidence_score_scenarios():
    """Verify confidence score calculations under various response payloads."""
    chunks = [Chunk(chunk_id="doc_123::0", doc_id="doc_123", text="Ref text")]
    happy_json = '{"answer": "Gemini generated answer.", "sources": ["doc_123"]}'

    # Scenario A: payload with >=2 top-candidates
    top_cands = [
        FakeTokenCandidate(log_probability=-0.1, token="A"),
        FakeTokenCandidate(log_probability=-1.5, token="B"),
    ]
    lr = FakeLogprobsResult(top_candidates=[FakeTopCandidatesEntry(candidates=top_cands)])
    candidates_a = [FakeCandidate(avg_logprobs=-0.5, logprobs_result=lr)]

    fake_client_a = FakeGeminiClient(response_text=happy_json, candidates=candidates_a)
    generator_a = GeminiGenerator(client=fake_client_a)
    _result, stats, raw = generator_a.generate_with_stats(chunks, "Question?")
    assert stats.confidence_score is not None
    # Margin: -0.1 - (-1.5) = 1.4
    assert stats.confidence_score == pytest.approx(1.4)
    # Check RawCall serialization
    assert raw.response["candidates"][0]["avg_logprobs"] == -0.5
    assert "logprobs_result" in raw.response["candidates"][0]

    # Scenario B: payload with only avg_logprobs (no usable top_candidates)
    candidates_b = [FakeCandidate(avg_logprobs=-0.75, logprobs_result=None)]
    fake_client_b = FakeGeminiClient(response_text=happy_json, candidates=candidates_b)
    generator_b = GeminiGenerator(client=fake_client_b)
    _, stats_b, raw_b = generator_b.generate_with_stats(chunks, "Question?")
    assert stats_b.confidence_score is not None
    assert stats_b.confidence_score == pytest.approx(-0.75)
    assert raw_b.response["candidates"][0]["avg_logprobs"] == -0.75
    assert "logprobs_result" not in raw_b.response["candidates"][0]

    # Scenario C: NO logprob payload (no candidates or logprobs)
    fake_client_c = FakeGeminiClient(response_text=happy_json, candidates=None)
    generator_c = GeminiGenerator(client=fake_client_c)
    _, stats_c, _ = generator_c.generate_with_stats(chunks, "Question?")
    assert stats_c.confidence_score is None

    # Scenario D: generate() still returns a bare AnswerWithSources
    fake_client_d = FakeGeminiClient(response_text=happy_json, candidates=candidates_a)
    generator_d = GeminiGenerator(client=fake_client_d)
    bare_res = generator_d.generate(chunks, "Question?")
    assert isinstance(bare_res, AnswerWithSources)
    assert bare_res.answer == "Gemini generated answer."

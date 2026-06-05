"""Unit tests for the cost-routing composite `RouterGenerator` (sprint-7/phase-2).

Covers AC-1..AC-7 and AC-11. Per ADR-0006 (AC-11) the router is exercised with two
injected **`Generator`-shaped fakes** — deterministic doubles that return a fixed
`(AnswerWithSources, CallStats, RawCall)` and count their calls. No `unittest.mock`, no
LLM-SDK doubles: the composite injects `Generator`-shaped objects, which is cleaner than
faking a provider SDK.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.raw_call import RawCall
from enterprise_rag_ops.eval.records import CallStats, Price, compute_cost_usd
from enterprise_rag_ops.generation.interfaces import Generator
from enterprise_rag_ops.generation.router_generator import RouterGenerator
from enterprise_rag_ops.generation.schema import ABSTAIN_ANSWER, AnswerWithSources

# --- Fixtures: prices, fixed sub-generator outputs -------------------------

_CHEAP_MODEL = "cheap-model"
_STRONG_MODEL = "strong-model"

_PRICES = {
    _CHEAP_MODEL: Price(input_usd_per_1m=1.0, output_usd_per_1m=2.0),
    _STRONG_MODEL: Price(input_usd_per_1m=10.0, output_usd_per_1m=20.0),
}

_CHEAP_STATS = CallStats(
    input_tokens=100, output_tokens=50, latency_s=0.10, model=_CHEAP_MODEL, system="google"
)
_STRONG_STATS = CallStats(
    input_tokens=200, output_tokens=80, latency_s=0.30, model=_STRONG_MODEL, system="anthropic"
)

_CHEAP_ANSWER = AnswerWithSources(answer="cheap answer", sources=["doc_1"])
_STRONG_ANSWER = AnswerWithSources(answer="strong answer", sources=["doc_2"])


class FakeGenerator:
    """A deterministic `Generator`-shaped double (ADR-0006, AC-11 — not an SDK mock).

    Returns a fixed `(AnswerWithSources, CallStats, RawCall)` and records how often it was
    called, so escalation-path tests can assert the strong generator ran zero or one time.
    `confidence_score` rides on the injected `CallStats` (the router reads it off there).
    """

    def __init__(self, answer: AnswerWithSources, stats: CallStats) -> None:
        self._answer = answer
        self._stats = stats
        self.call_count = 0
        self._raw = RawCall(request={"model": stats.model}, response={"answer": answer.answer})

    def generate(self, context_chunks, question):
        result, _, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(self, context_chunks, question):
        self.call_count += 1
        return self._answer, self._stats, self._raw


def _cheap_stats(confidence: float | None) -> CallStats:
    return _CHEAP_STATS.model_copy(update={"confidence_score": confidence})


def _make_router(cheap: FakeGenerator, strong: FakeGenerator, threshold: float = 1.0):
    return RouterGenerator(
        cheap=cheap,
        strong=strong,
        prices=_PRICES,
        cheap_model_id=_CHEAP_MODEL,
        strong_model_id=_STRONG_MODEL,
        threshold=threshold,
    )


# Expected per-call costs (recomputed independently of the router for cross-checks).
_CHEAP_COST = compute_cost_usd(_CHEAP_STATS, _PRICES[_CHEAP_MODEL])
_STRONG_COST = compute_cost_usd(_STRONG_STATS, _PRICES[_STRONG_MODEL])


# --- AC-1: no-escalation path ----------------------------------------------


def test_no_escalation_when_confident_and_not_abstaining():
    """AC-1: confidence == threshold and a non-abstaining answer → strong is NOT called."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(1.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    answer, stats, raw = router.generate_with_stats([], "q?")

    assert strong.call_count == 0
    assert answer == _CHEAP_ANSWER
    assert stats.model == "router"
    assert stats.system == "router"
    assert stats.input_tokens == _CHEAP_STATS.input_tokens
    assert stats.output_tokens == _CHEAP_STATS.output_tokens
    assert stats.latency_s == _CHEAP_STATS.latency_s
    assert stats.cost_usd == _CHEAP_COST
    # FR-7: gen_raw is the cheap call's RawCall.
    assert raw.request["model"] == _CHEAP_MODEL


# --- AC-2: escalation on low confidence ------------------------------------


def test_escalation_on_low_confidence():
    """AC-2: confidence < threshold → strong is called; answer + sums are the combined."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(0.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    answer, stats, raw = router.generate_with_stats([], "q?")

    assert strong.call_count == 1
    assert answer == _STRONG_ANSWER
    assert stats.input_tokens == _CHEAP_STATS.input_tokens + _STRONG_STATS.input_tokens
    assert stats.output_tokens == _CHEAP_STATS.output_tokens + _STRONG_STATS.output_tokens
    assert stats.latency_s == _CHEAP_STATS.latency_s + _STRONG_STATS.latency_s
    assert stats.cost_usd == _CHEAP_COST + _STRONG_COST
    # FR-7: gen_raw is still the cheap call's RawCall even when escalated.
    assert raw.request["model"] == _CHEAP_MODEL


# --- AC-3: escalation on abstention (OR-trigger, independent of confidence) -


def test_escalation_on_abstention_even_when_confident():
    """AC-3: cheap answer == ABSTAIN_ANSWER escalates even with confidence == 1.0."""
    abstain_answer = AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[])
    cheap = FakeGenerator(abstain_answer, _cheap_stats(1.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    answer, _, _ = router.generate_with_stats([], "q?")

    assert strong.call_count == 1
    assert answer == _STRONG_ANSWER


# --- AC-4: escalation on missing confidence --------------------------------


def test_escalation_on_missing_confidence():
    """AC-4: confidence_score is None → escalate (no silent pass-through)."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(None))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    answer, _, _ = router.generate_with_stats([], "q?")

    assert strong.call_count == 1
    assert answer == _STRONG_ANSWER


# --- AC-5: combined-cost arithmetic ----------------------------------------


def test_combined_cost_arithmetic_escalated():
    """AC-5: escalated cost == cheap_cost + strong_cost; confidence == the cheap call's."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(0.5))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    _, stats, _ = router.generate_with_stats([], "q?")

    expected = compute_cost_usd(_CHEAP_STATS, _PRICES[_CHEAP_MODEL]) + compute_cost_usd(
        _STRONG_STATS, _PRICES[_STRONG_MODEL]
    )
    assert stats.cost_usd == expected
    assert stats.confidence_score == 0.5


def test_combined_cost_arithmetic_not_escalated():
    """AC-5: non-escalated cost == exactly cheap_cost; confidence == the cheap call's."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(1.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    _, stats, _ = router.generate_with_stats([], "q?")

    assert stats.cost_usd == compute_cost_usd(_CHEAP_STATS, _PRICES[_CHEAP_MODEL])
    assert stats.confidence_score == 1.0


# --- AC-6: generate() returns a bare AnswerWithSources ----------------------


def test_generate_returns_bare_answer_no_escalation():
    """AC-6: generate() returns the same bare answer generate_with_stats would (cheap path)."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(1.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    result = router.generate([], "q?")

    assert isinstance(result, AnswerWithSources)
    assert result == _CHEAP_ANSWER


def test_generate_returns_bare_answer_escalated():
    """AC-6: generate() returns the strong answer on the escalated path."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(0.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong, threshold=1.0)

    result = router.generate([], "q?")

    assert isinstance(result, AnswerWithSources)
    assert result == _STRONG_ANSWER


# --- AC-7: structural Protocol conformance ---------------------------------


def test_router_is_structural_generator():
    """AC-7: RouterGenerator conforms to the @runtime_checkable Generator Protocol."""
    cheap = FakeGenerator(_CHEAP_ANSWER, _cheap_stats(1.0))
    strong = FakeGenerator(_STRONG_ANSWER, _STRONG_STATS)
    router = _make_router(cheap, strong)

    assert isinstance(router, Generator)

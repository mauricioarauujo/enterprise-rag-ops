"""Cost-routing composite `Generator` (sprint-7/phase-2, FR-1..FR-5, FR-7).

`RouterGenerator` answers with a cheap sub-generator by default and escalates to a strong
sub-generator only when the cheap answer is not trustworthy (ADR-0011 §5: confidence below
threshold, missing confidence, or abstention).

It is the single owner of *combined* cost: it is the only site that holds both sub-`CallStats`
objects and the price table at once, so it manufactures one output `CallStats` that charges
the cheap call **always** and the strong call **iff** escalated. This enforces the #1
research-fairness rule (Bouchard 2026 Q6): the cheap call is never dropped on an escalated
query, and the strong call is never double-counted.

Constructed by composition/injection (Approach B): it holds two injected `Generator`
instances and conforms to the `Generator` Protocol *structurally* via `generate` — it does
not inherit, register in `_GENERATOR_FACTORY`, or touch `interfaces.py` (NFR-1, AC-7).
"""

from __future__ import annotations

from enterprise_rag_ops.eval.raw_call import RawCall
from enterprise_rag_ops.eval.records import CallStats, Price, compute_cost_usd
from enterprise_rag_ops.generation.interfaces import Generator
from enterprise_rag_ops.generation.schema import ABSTAIN_ANSWER, AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

# Synthetic identity for the manufactured combined CallStats (FR-5, FR-10). The router is
# not a real provider/model; "router"/"router" is what the runner also stamps on the
# EvalRecord.gen_ai for the router sweep row.
ROUTER_MODEL_ID = "router"
ROUTER_SYSTEM = "router"


class RouterGenerator:
    """A cheap-default, escalate-on-low-trust composite `Generator` (FR-1).

    Holds two injected `Generator` instances (`cheap`, `strong`), the escalation
    `threshold`, the price table, and the cheap/strong model ids it uses to look prices up.
    No factory lookup happens inside the class — sub-generators and prices are injected.
    """

    def __init__(
        self,
        cheap: Generator,
        strong: Generator,
        prices: dict[str, Price],
        cheap_model_id: str,
        strong_model_id: str,
        threshold: float = 1.0,
    ) -> None:
        self._cheap = cheap
        self._strong = strong
        self._prices = prices
        self._cheap_model_id = cheap_model_id
        self._strong_model_id = strong_model_id
        self._threshold = threshold

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Return the bare cheap-or-strong `AnswerWithSources` (FR-3).

        Delegates to `generate_with_stats` and drops the stats/raw — exactly mirroring the
        concrete generators' `generate`. This is what makes `RouterGenerator` a structural
        `Generator` (duck-typed; no change to `interfaces.py`).
        """
        result, _, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats, RawCall]:
        """Route the query and return the combined `(answer, CallStats, RawCall)` (FR-2).

        Calls the cheap generator always; applies the escalation rule (FR-4); calls the
        strong generator only when escalating; returns the strong answer when escalated else
        the cheap answer, with the manufactured combined `CallStats` (FR-5) and the cheap
        call's `RawCall` as `gen_raw` (FR-7).
        """
        cheap_ans, cheap_stats, cheap_raw = self._cheap.generate_with_stats(
            context_chunks, question
        )

        # FR-4 / ADR-0011 §5: escalate unless the cheap model was confident (>= threshold)
        # AND did not abstain. Missing confidence is treated as not-confident (a non-Gemini
        # cheap generator, or a parse miss, must not silently pass through — AC-4).
        escalate = (
            cheap_stats.confidence_score is None
            or cheap_stats.confidence_score < self._threshold
            or cheap_ans.answer == ABSTAIN_ANSWER
        )

        # FR-5: the cheap call is charged ALWAYS; the strong call only when escalated.
        cheap_cost = compute_cost_usd(cheap_stats, self._prices.get(self._cheap_model_id))

        if escalate:
            strong_ans, strong_stats, _ = self._strong.generate_with_stats(context_chunks, question)
            strong_cost = compute_cost_usd(strong_stats, self._prices.get(self._strong_model_id))
        else:
            strong_ans, strong_stats, strong_cost = None, None, None

        answer = strong_ans if escalate else cheap_ans

        # Manufacture one combined CallStats (FR-5). None cost summands → 0.0, mirroring the
        # runner's `(x or 0.0)` convention; the strong summands are included iff escalated.
        combined_stats = CallStats(
            input_tokens=cheap_stats.input_tokens + (strong_stats.input_tokens if escalate else 0),
            output_tokens=cheap_stats.output_tokens
            + (strong_stats.output_tokens if escalate else 0),
            latency_s=cheap_stats.latency_s + (strong_stats.latency_s if escalate else 0.0),
            model=ROUTER_MODEL_ID,
            system=ROUTER_SYSTEM,
            cost_usd=(cheap_cost or 0.0) + ((strong_cost or 0.0) if escalate else 0.0),
            confidence_score=cheap_stats.confidence_score,
        )

        return answer, combined_stats, cheap_raw

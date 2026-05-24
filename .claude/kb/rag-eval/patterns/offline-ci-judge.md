# Offline-CI Judge Testing

> **Purpose**: Keep `make test` network-free and key-free while still testing the
> judge contract, prompt shape, and the anchor case — using `StubJudge` and an
> injected `FakeOpenAIClient`.
> **MCP Validated**: 2026-05-24

## When to Use

- CI and `make test` (no `OPENAI_API_KEY`, no network).
- Unit tests that assert call shape, prompt content, or schema wiring.
- The anchor case (spurious citation) — provable without a live LLM call.

## Two Offline Testing Modes

### Mode 1: `StubJudge` via the `Judge` seam

`StubJudge` returns a deterministic `JudgeVerdict` (every fact `present`, every
citation `supported`) with no API call. Drop-in for `OpenAIJudge` anywhere the
`Judge` Protocol is expected.

```python
# tests/eval/test_judge_contract.py
from enterprise_rag_ops.eval.stub_judge import StubJudge
from enterprise_rag_ops.eval.interfaces import Judge

judge: Judge = StubJudge()
verdict = judge.judge(
    question="Q",
    answer_with_sources=sample_answer,
    answer_facts=["fact 1", "fact 2"],
    retrieved_docs=sample_chunks,
)
assert verdict.fact_recall == 1.0
assert verdict.faithfulness_ratio == 1.0
assert all(f.verdict == "present" for f in verdict.per_fact)
assert all(c.verdict == "supported" for c in verdict.per_citation)
```

### Mode 2: `FakeOpenAIClient` injected into `OpenAIJudge`

Used for call-shape and prompt assertions: confirms exactly one `create` call was
made, `strict: True` was set, and the prompt rendered per-`doc_id` blocks correctly.

```python
# tests/eval/conftest.py — the shared fake client
class FakeOpenAIClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
```

```python
# tests/eval/test_openai_judge.py — usage pattern
def test_single_call_strict_schema(canned_verdict_payload, sample_answer,
                                   sample_facts, sample_chunks):
    client = FakeOpenAIClient(canned_verdict_payload)
    OpenAIJudge(client=client).judge(
        question="Q", answer_with_sources=sample_answer,
        answer_facts=sample_facts, retrieved_docs=sample_chunks,
    )
    assert len(client.calls) == 1
    rf = client.calls[0]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    # Floats must NOT appear in the schema sent to the LLM
    schema = rf["json_schema"]["schema"]
    assert "fact_recall" not in schema.get("properties", {})
```

## The Anchor Case (Hand-Built Verdicts)

The spurious-citation thesis is provable without any LLM call — build verdicts by
hand, run through `aggregate`, assert the result:

```python
# tests/eval/test_judge_anchor.py — proof 1 (hand-built, non-circular)
from enterprise_rag_ops.eval.aggregate import aggregate
from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict

per_fact = [FactVerdict(fact="Paris is the capital of France.", verdict="present")]
per_citation = [
    CitationVerdict(doc_id="doc_real", verdict="supported"),
    CitationVerdict(doc_id="gd_unrelated", verdict="unsupported"),
]
_, _, faithfulness = aggregate(per_fact, per_citation)
assert faithfulness == 0.5
assert faithfulness < 1.0
```

## The Cassette/Replay Path (Should-Tier)

A `vcrpy` cassette records a real `OpenAIJudge` call and replays it under `make test`.
This is Should-tier (its absence does not fail CI): `StubJudge` + `FakeOpenAIClient`
carry the contract offline.

Why `vcrpy` was deferred (ADR-0001): a cassette cannot be recorded without a live
call, so adding the dev dependency unused was declined per `CLAUDE.md`
§ Engineering Behavior. Wire it when the first live judge call is made.

```python
# When landed: gate the live-record path behind a marker
@pytest.mark.cassette  # excluded from make test's default pytest run
def test_live_openai_judge_cassette(vcr):
    with vcr.use_cassette("tests/cassettes/judge_anchor.yaml"):
        verdict = OpenAIJudge().judge(...)
    assert verdict.faithfulness_ratio < 1.0
```

## Invariant: `openai` import isolation

All non-`openai_judge` eval modules (`schema`, `aggregate`, `interfaces`, `prompt`,
`stub_judge`, `questions`) must never import `openai`. This preserves the offline-CI
invariant on a clean clone without the SDK installed.

```python
# Verify no stray import (run in CI)
import ast, pathlib
for p in pathlib.Path("src/enterprise_rag_ops/eval").glob("*.py"):
    if p.name == "openai_judge.py":
        continue
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            assert not any("openai" in n for n in names), f"Stray openai import in {p}"
```

## See Also

- [../concepts/schema-as-ssot.md](../concepts/schema-as-ssot.md)
- [per-fact-judge-call.md](per-fact-judge-call.md)
- `eval/stub_judge.py`, `eval/interfaces.py`
- `tests/eval/conftest.py`, `tests/eval/test_judge_anchor.py`

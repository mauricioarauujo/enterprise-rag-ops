# Cassette/Replay for Offline Eval of Live-LLM Tests

> **Purpose**: Record a real LLM response once, commit the YAML cassette, and replay
> it in CI without a network or API key — while staying honest about what is and is
> not tested.
> **Codebase**: `tests/conftest.py` (`vcr_record` fixture — root, shared across suite),
> `tests/eval/cassettes/abstention_info_not_found.yaml`,
> `pyproject.toml` (`vcrpy`, `vcr` marker)
> **ADR**: `docs/adr/0006-cassette-replay.md`

## When to Use Cassettes vs. Fakes

Both cassettes (vcrpy) and fakes (`StubJudge` / `FakeOpenAIClient`) keep tests
offline. They test different things:

| Technique          | What it tests                                          | What it cannot test            |
| ------------------ | ------------------------------------------------------ | ------------------------------ |
| `StubJudge`        | Protocol contract, call shape, aggregation logic       | Actual model response content  |
| `FakeOpenAIClient` | Prompt rendering, `strict` schema, call count          | Actual model response content  |
| vcrpy cassette     | Actual recorded model response (exact text, structure) | Prompt changes after recording |

**The boundary rule:** a fake is appropriate for call-shape and prompt assertions.
Any test that asserts on the model's actual response content — e.g. "the generator
emits `ABSTAIN_ANSWER` when context is insufficient" — requires a real recorded
cassette. A hand-fabricated cassette with invented content is functionally a mock
and silently degrades to the testing mode it was meant to replace.

This failure was caught in Phase-5 review: the original hand-built cassette contained
a `2023` timestamp, a fake `chatcmpl-vcr-mocked-id`, and `body: null` — none of which
a real OpenAI response produces. When replaced with a genuine recording, the real
model response was free-form ("The provided context does not contain…"), not the
sentinel, exposing a generator design defect.

## vcrpy Wiring (from root `tests/conftest.py`)

The `vcr_record` fixture lives in the **root `tests/conftest.py`** (not under
`tests/eval/`), so it is shared across the entire test suite with a single scrubbing
policy.

```python
# tests/conftest.py  (Phase 6 — canonical location)
_FILTER_REQUEST_HEADERS = ["authorization", "x-api-key"]

_SCRUB_RESPONSE_HEADERS = {
    "anthropic-organization-id", "openai-organization",
    "set-cookie", "cf-ray", "request-id",
}

def _scrub_response(response: dict) -> dict:
    """Drop identifying response headers before a cassette is written."""
    headers = response.get("headers")
    if headers:
        for name in list(headers):
            if name.lower() in _SCRUB_RESPONSE_HEADERS:
                headers.pop(name)
    return response

@pytest.fixture
def vcr_record() -> vcr.VCR:
    return vcr.VCR(
        cassette_library_dir="tests/eval/cassettes",
        record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
        filter_headers=_FILTER_REQUEST_HEADERS,
        before_record_response=_scrub_response,
    )
```

Key choices:

- `record_mode="none"` by default — raises `CannotSendRequest` if no cassette or
  if the request does not match. Tests fail, never silently hit the network.
- `filter_headers` covers both OpenAI (`authorization`) and Anthropic (`x-api-key`).
- `before_record_response` scrubs account-identifying response headers
  (`anthropic-organization-id`, `set-cookie`, etc.). vcrpy 6 has no
  `filter_response_headers` kwarg — response scrubbing requires `before_record_response`.
- `cassette_library_dir` — cassettes live in `tests/eval/cassettes/` and are
  committed to the repository.

## Using a Cassette in a Test

```python
# tests/eval/test_abstention.py
@pytest.mark.vcr  # selection label only — the fixture applies the cassette
def test_e2e_abstention_paris_anchor(vcr_record):
    with vcr_record.use_cassette("abstention_info_not_found.yaml"):
        answer = generator.generate(context_chunks, question)
    assert answer.answer == ABSTAIN_ANSWER
    assert answer.sources == []
```

Note: `@pytest.mark.vcr` is a custom marker used for test selection
(`-m vcr` to run only cassette tests, `-m "not vcr"` to skip them). vcrpy 6 does
not ship a pytest plugin that reads this marker — the cassette is applied by the
`vcr_record` fixture's `use_cassette` context manager.

## Recording a New Cassette

1. Set the env var: `VCR_RECORD_MODE=once uv run pytest tests/eval/test_abstention.py -m vcr`
2. vcrpy intercepts the real HTTP call, records to
   `tests/eval/cassettes/<name>.yaml`, and strips `Authorization`.
3. The test passes on the live network; subsequent runs replay offline.
4. Commit the cassette YAML. Cost: one real API call, typically < $0.01.

Re-record when: prompt templates or schemas change (the recorded request body
will no longer match the new one — vcrpy raises `CannotSendRequest` in `"none"` mode,
which is the signal to re-record).

## Validating a Genuine Cassette

A genuine cassette (as opposed to hand-fabricated) has:

- Real request headers (`x-stainless-arch`, `x-request-id`, `openai-organization`, etc.)
- No `Authorization` header (filtered out)
- A real response body with `id: chatcmpl-<real-id>` and a real timestamp
- The actual model-emitted content in `body.string`

A hand-fabricated cassette that fails these checks is a mock in disguise.

## See Also

- [offline-ci-judge.md](offline-ci-judge.md) — fakes and stubs (the complement)
- [../concepts/abstention-scoring.md](../concepts/abstention-scoring.md)
- `docs/adr/0006-cassette-replay.md`
- `tests/conftest.py` — root fixture (shared VCR config, response scrubbing)
- `tests/eval/cassettes/` — committed cassette YAMLs

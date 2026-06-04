# add-a-generator

> **Purpose**: The complete recipe to add a fourth LLM provider behind the Generator seam — the localized swap the seam promises.
> **MCP Validated**: 2026-06-01

## When to Use

- Adding a new LLM provider to the multi-model evaluation sweep.
- Swapping the structured-output mechanism for an existing provider.
- Wiring a local/Ollama model behind the same seam without touching the eval runner logic.

## Implementation

### Step 1 — New `<provider>_generator.py`

Create `src/enterprise_rag_ops/generation/<provider>_generator.py`. Follow the exact structure of the existing three implementations:

```python
DEFAULT_MODEL = "<provider-default-model-id>"

class <Provider>Generator:
    def __init__(self, model: str | None = None, client=None) -> None:
        if client is None:
            if not os.environ.get("<PROVIDER>_API_KEY"):
                raise RuntimeError(
                    "<PROVIDER>_API_KEY is not set — required for <Provider>Generator."
                )
            # Retry hardening — mirror the pattern for your provider's throttle risk.
            # Anthropic: Anthropic(max_retries=8, timeout=120.0)
            # Gemini: genai.Client(http_options=types.HttpOptions(
            #     timeout=120_000,
            #     retry_options=types.HttpRetryOptions(attempts=8, http_status_codes=[429,...])
            # ))
            client = <ProviderSDK>(...)
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL_<PROVIDER>", DEFAULT_MODEL)

    def generate(self, context_chunks, question) -> AnswerWithSources:
        result, _, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(self, context_chunks, question):
        system_prompt = build_system_prompt()   # shared, model-agnostic
        user_prompt = build_user_prompt(context_chunks, question)

        start_time = time.perf_counter()
        response = self._client.<call>(...)     # provider-specific structured-output call
        latency = time.perf_counter() - start_time

        # Always re-validate our side — regardless of provider-side enforcement.
        result = AnswerWithSources.model_validate_json(response.<text_field>)

        # Defensive token reads — provider field names differ (see concepts/).
        usage = getattr(response, "<usage_attr>", None)
        input_tokens  = getattr(usage, "<input_field>", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "<output_field>", 0) or 0 if usage else 0

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="<provider_key>",   # must match the _GENERATOR_FACTORY key
        )

        # Raw payload capture — build request from local vars (never from client),
        # serialize response with _serialize_response (see concepts/).
        request = {
            "model": self._model,
            "<messages_key>": <local_messages_var>,
            # include only params actually sent to the SDK call
        }
        raw_call = RawCall(request=request, response=_serialize_response(response))
        return result, stats, raw_call
```

**Structured-output guidance by mechanism:**

- OpenAI-compatible JSON schema: use `response_format={"type":"json_schema","json_schema":{"name":...,"schema":AnswerWithSources.model_json_schema(),"strict":True}}`.
- Tool-use (Anthropic-style): define `tools=[{"name":"emit_answer","input_schema":schema}]` and force with `tool_choice={"type":"tool","name":"emit_answer"}`; parse `block.input` as a dict.
- Native response schema that rejects `additionalProperties`: define an open mirror (no `extra="forbid"`), pass the mirror to the SDK, enforce closed-schema our side via `model_validate_json`. See `concepts/structured-output-per-provider.md`.

### Step 2 — Wire the factory

```python
# eval/runner.py — one line
_GENERATOR_FACTORY = {
    "openai":     OpenAIGenerator,
    "anthropic":  AnthropicGenerator,
    "google":     GeminiGenerator,
    "<provider>": <Provider>Generator,   # add this line + the import above
}
```

### Step 3 — Widen `ModelConfig.system` Literal

```python
# eval/config.py
class ModelConfig(BaseModel):
    system: Literal["openai", "anthropic", "google", "<provider>"]
    model_id: str
```

### Step 4 — Add a price row in `configs/baseline.yaml`

```yaml
prices:
  <provider-model-id>:
    input_usd_per_1m: <float>
    output_usd_per_1m: <float>
```

Without a price row, `compute_cost_usd` returns `None` and logs a warning (cost-accounting does not crash the sweep).

### Step 5 — Env-key fail-fast guard

The `RuntimeError` on missing env key must use the exact provider env var name (`<PROVIDER>_API_KEY` or `RAG_GEN_MODEL_<PROVIDER>` for model override). This surfaces misconfiguration before the sweep touches the network.

### Step 6 — Retry hardening

Born from real sweep throttling on Anthropic (tier-1 output-token/min) and Gemini (transient 503):

- **Anthropic pattern:** `Anthropic(max_retries=8, timeout=120.0)` — the SDK honours `retry-after` with backoff.
- **Gemini pattern:** `genai.Client(http_options=types.HttpOptions(timeout=120_000, retry_options=types.HttpRetryOptions(attempts=8, http_status_codes=[429,500,502,503,504])))`.
- For providers with SDK-level retry knobs, set `attempts=8` and include all 5xx codes.
- `timeout=120` seconds (or 120_000 ms) bounds a single call so a dead socket fails fast instead of blocking a thread indefinitely.

### Step 7 — Record a cassette and scrub the provider's key transport

```python
# tests/conftest.py — add the provider's credential header
_FILTER_REQUEST_HEADERS = [
    "authorization",    # OpenAI
    "x-api-key",        # Anthropic
    "x-goog-api-key",   # Google
    "<provider-header>",
]
_FILTER_QUERY_PARAMS = ["key", "<provider-query-param>"]
```

Record the cassette once with `VCR_RECORD_MODE=once`; commit the scrubbed YAML to `tests/eval/cassettes/<provider>_generator.yaml`. All subsequent CI runs replay offline.

See `rag-eval` → `patterns/cassette-replay-eval.md` for the full cassette workflow.

## Configuration

| Setting                    | Where                                | Description                                     |
| -------------------------- | ------------------------------------ | ----------------------------------------------- |
| `DEFAULT_MODEL`            | `<provider>_generator.py`            | Module-level default; lowest-cost model         |
| `RAG_GEN_MODEL_<PROVIDER>` | env var                              | Runtime override; explicit constructor arg wins |
| Price entry                | `configs/baseline.yaml`              | Required for cost tracking; `None` if missing   |
| `system` key               | `_GENERATOR_FACTORY` + `ModelConfig` | Must be identical in both places                |

## See Also

- [concepts/generator-seam.md](../concepts/generator-seam.md) — the Protocol and what "localized swap" means
- [concepts/structured-output-per-provider.md](../concepts/structured-output-per-provider.md) — structured-output mechanism options
- [concepts/per-provider-token-accounting.md](../concepts/per-provider-token-accounting.md) — token-field mapping reference
- [concepts/raw-payload-serialization.md](../concepts/raw-payload-serialization.md) — RawCall model, \_serialize_response algorithm, privacy guarantee
- `rag-eval` → `patterns/cassette-replay-eval.md` — cassette recording workflow
- ADR-0003 (`docs/adr/0003-generation.md`) — seam design and swap scope

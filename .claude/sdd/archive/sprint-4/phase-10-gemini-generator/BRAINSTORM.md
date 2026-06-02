# BRAINSTORM: phase-10-gemini-generator — Third Generator (GeminiGenerator)

**Sprint/Phase:** sprint-4/phase-10-gemini-generator | **Date:** 2026-06-01

---

## Problem Statement

The multi-model eval sweep currently compares only two generator families (OpenAI +
Anthropic), which means the "multi-model" dashboard degrades to a single-pair report.
Adding `gemini-2.5-flash-lite` behind the existing `Generator` Protocol turns it into a
genuine three-way comparison and strengthens the evidence Sprint 4 needs before the
README + writeup phases. The seam is already proven: the change is a new file
(`gemini_generator.py`) + one-line dict entry in `runner.py` + extending the
`system` Literal in `config.py` + price entry in `baseline.yaml`.

---

## Suggested Research & KB Work

| Topic                                                                                                                                       | Coverage                                                                                                          | Action                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `google-genai` SDK — `generate_content`, `GenerateContentConfig`, `response_schema` vs `response_json_schema`, `usage_metadata` field names | **Missing** — no KB domain yet                                                                                    | Context7 MCP lookup on `google-genai` (already planned in SPRINT.md knowledge plan; no `--deep-research` needed — SDK is well-documented) |
| `Generator` Protocol + `generate_with_stats` contract                                                                                       | **Sufficient** — `rag-eval` KB covers `stats-capture-seam` + `AnthropicGenerator` is the template in the codebase | No new KB needed; read `anthropic_generator.py` as the template                                                                           |
| Cassette/replay pattern (ADR-0006)                                                                                                          | **Sufficient** — `rag-eval` KB `cassette-replay-eval` pattern                                                     | Reuse; no new KB                                                                                                                          |
| `rag-generation` KB domain (Generator seam, structured-output-per-provider, multi-provider contract)                                        | **Missing** — scaffold exists but content is empty (carried from Sprint 2 and 3)                                  | `/new-kb rag-generation` **after** Phase 10 ADR/impl — three providers make the pattern concrete; not a blocker for this phase            |

---

## Approaches Considered

The meaningful design forks are (1) structured-output mechanism and (2) whether to
re-run the full sweep in this phase or defer the 3-way published numbers.

### Structured-output mechanism

| Approach                                                                                                                                  | Pros                                                                                                                                                                                                                     | Cons                                                                                                                                                                                   | Effort          |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| **A — Native JSON schema mode** (`response_schema=AnswerWithSources` in `GenerateContentConfig`, `response_mime_type="application/json"`) | Simplest implementation: no tool wrapper, no schema serialisation boilerplate; Pydantic model passed directly; `model_validate_json(resp.text)` enforces `extra="forbid"` on our side regardless of provider enforcement | `response_schema` vs `response_json_schema` variant must be confirmed against the live SDK at design time; must verify `usage_metadata` field names for token accounting               | S               |
| **B — Function/tool-calling** (mirror `AnthropicGenerator` forced tool-use)                                                               | Consistent pattern with Anthropic side; tool-use guarantees structured response                                                                                                                                          | More boilerplate (tool dict, tool_choice forcing, parsing `function_call` from response); Gemini tool-calling API differs from Anthropic's tool_use block structure; no benefit over A | M               |
| **C — Raw-prompt + JSON parse** (instruct model in prompt, `json.loads` the response)                                                     | Zero SDK-specific code                                                                                                                                                                                                   | Fragile: model may wrap JSON in markdown fences or add commentary; requires defensive stripping; `extra="forbid"` alone cannot prevent schema drift; no reliability guarantee          | S (but brittle) |

**Recommendation:** Approach A. The `google-genai` SDK explicitly supports passing a
Pydantic model as `response_schema`; it is simpler than Anthropic forced tool-use and
more reliable than raw-prompt parse. The only confirmation needed at `/design` is which
SDK variant (`response_schema` vs `response_json_schema`) is live in the pinned
`google-genai` version.

### Default sweep matrix (re-run cost/timing)

| Approach                                                                              | Pros                                                                                                                                                 | Cons                                                                                                                               | Effort |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **X — Add Gemini to `baseline.yaml` now + re-run the full 500-q sweep in Phase 10**   | Published baseline becomes 3-way immediately; Phase 11 README uses real 3-way numbers                                                                | Re-running 500 questions costs ~$0.10–0.15 (flash-lite pricing) + ~2–3h of compute on the 8 GB Air; this is the Phase 10 time cost | M      |
| **Y — Add Gemini to `baseline.yaml` but defer the re-run to Phase 11 (README phase)** | Phase 10 stays focused on the implementation + cassette + ADR; re-run happens at the point it is needed (Phase 11's "published numbers" requirement) | Small coordination overhead; Phase 11 must not start writing numbers before the sweep completes                                    | S      |

**Recommendation:** Approach X — add Gemini to `baseline.yaml` and run the 3-way sweep
in Phase 10. The re-run cost is trivial ($0.10–0.15), and having 3-way JSONL committed
before Phase 11 lets the README phase work from real evidence without a blocking
dependency. The sweep can be gated behind the cassette being recorded.

---

## Recommended Approach

**Approach A + Approach X:**

1. Implement `GeminiGenerator` using native JSON schema mode (`response_schema=
AnswerWithSources` in `GenerateContentConfig`). Client init reads `GEMINI_API_KEY`
   (confirm exact env var name at design). Default model `gemini-2.5-flash-lite`,
   overridable via `RAG_GEN_MODEL_GOOGLE`. Token accounting reads `usage_metadata`
   from the response (field names confirmed at design). `system="google"` in
   `CallStats` and `gen_ai.system` (provider-family naming, not model-name — rationale
   below).
2. Wire into `runner.py` (`_GENERATOR_FACTORY["google"] = GeminiGenerator`) and extend
   the `system` Literal in `config.py` to `Literal["openai", "anthropic", "google"]`.
3. Add `gemini-2.5-flash-lite` to `configs/baseline.yaml` (models list + price entry:
   0.10 input / 0.40 output per 1M). Run the full 3-way sweep in Phase 10.
4. Amend ADR-0005 to record Google/Gemini as the third generator family and restate the
   independence constraint (Gemini never judges).
5. Record one live cassette; CI replays offline.

**On `system` naming — `"google"` vs `"gemini"`:** use `"google"`. Rationale: `CallStats.system`
flows to `GenAiFields.system` which flows to the observability span attribute
`gen_ai.system`. The OTel GenAI semantic conventions name this field as the provider
family (e.g. `"openai"`, `"anthropic"`, `"google_vertexai"`, `"google_generativeai"`),
not the model series. Consistency with the existing `"openai"` and `"anthropic"` keys
in `_GENERATOR_FACTORY` also argues for `"google"`. If the SDK's own attribute is
`"google_generativeai"`, that is a detail to confirm at design — the Literal key and
factory key should be `"google"` regardless, for brevity and symmetry.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                             |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | `GeminiGenerator` class in `generation/gemini_generator.py` implementing `generate` + `generate_with_stats`                                                      |
| **Must**   | Wire into `runner.py` `_GENERATOR_FACTORY` dict                                                                                                                  |
| **Must**   | Extend `system` Literal in `eval/config.py` to include `"google"`                                                                                                |
| **Must**   | `google-genai` dep added to `pyproject.toml`                                                                                                                     |
| **Must**   | `GEMINI_API_KEY` env guard (fail-fast in `__init__`, mirroring `AnthropicGenerator`)                                                                             |
| **Must**   | `RAG_GEN_MODEL_GOOGLE` env override (mirroring `RAG_GEN_MODEL_ANTHROPIC`)                                                                                        |
| **Must**   | Price entry for `gemini-2.5-flash-lite` in `configs/baseline.yaml`                                                                                               |
| **Must**   | One recorded cassette + `tests/generation/test_gemini_generator.py` (ADR-0006 compliance)                                                                        |
| **Must**   | Amend ADR-0005: add Google as third generator family + restate independence constraint                                                                           |
| **Should** | Add `gemini-2.5-flash-lite` to `baseline.yaml` models list + run the full 3-way sweep in Phase 10 so Phase 11 has real published numbers                         |
| **Could**  | Commit the 3-way baseline JSONL to `results/` (or document as gitignored regenerable artifact)                                                                   |
| **Could**  | `/new-kb rag-generation` after the ADR lands — Phase 10 is the natural home (three providers make the pattern concrete)                                          |
| **Won't**  | Gemini as judge — violates judge/generator independence (ADR-0005 constraint); same-family bias risk is exactly what the ADR exists to prevent                   |
| **Won't**  | Batch-mode API — breaks the synchronous `Generator` Protocol seam; the 500-question sweep cost is trivially small, so async batch provides no meaningful savings |
| **Won't**  | Ollama or any other new provider in this phase — scope is exactly the third cloud family                                                                         |
| **Won't**  | Modifying the `Generator` Protocol in `interfaces.py` — the seam is proven; no changes needed                                                                    |

---

## Open Questions

1. **`response_schema` vs `response_json_schema`:** The `google-genai` SDK has evolved
   its structured-output API. Which parameter name is live in the version we will pin?
   Does the `GenerateContentConfig` accept `AnswerWithSources` (a Pydantic model) directly,
   or does it require a JSON Schema dict? Confirm via Context7 at `/design`.

2. **`usage_metadata` field names:** Does the `GenerateContent` response expose token
   counts as `usage_metadata.prompt_token_count` / `usage_metadata.candidates_token_count`,
   or under different keys? The `CallStats` fields are `input_tokens` / `output_tokens` —
   the mapping must be confirmed before the generator can produce accurate cost accounting.

3. **Env var name:** Is the canonical env var `GEMINI_API_KEY` or `GOOGLE_API_KEY`?
   The `google-genai` client constructor may accept either or prefer one. Confirm at
   design — the fail-fast guard in `__init__` depends on this.

4. **`gen_ai.system` value for observability:** OTel GenAI semantic conventions list
   `"google_generativeai"` as a known system value. Should `CallStats.system` (and the
   factory key) be the short `"google"` (symmetric with `"openai"`, `"anthropic"`) or
   the conventions-exact `"google_generativeai"`? This affects how the span attribute
   reads in Phoenix. Decide at `/define` — it is a one-character-level config choice
   but must be consistent across `_GENERATOR_FACTORY`, the Literal, and the observability
   span tree.

5. **3-way sweep timing:** Should the full 3-way sweep (500 questions, ~$0.15 estimated)
   be run and its JSONL committed in Phase 10, or blocked until Phase 11 (README phase)
   where the numbers are actually consumed? Phase 11 has a hard dependency on these
   results — if Phase 10 slips, Phase 11 cannot write the published numbers.

---

## Infra Gaps

- `google-genai` is not in `pyproject.toml` — must be added as a new dep.
- `rag-generation` KB domain scaffold exists but is empty (carried debt from Sprint 2
  and Sprint 3). Phase 10 is the natural home for the first content pass (three
  providers make the `generate_with_stats` pattern concrete). This is a Should item,
  not a Must — it must not block the generator implementation.
- ADR-0005 currently covers OpenAI, Anthropic, Ollama — the Google addition is an
  amendment, not a new ADR.

---

## Next Step

→ `/define sprint-4/phase-10-gemini-generator`

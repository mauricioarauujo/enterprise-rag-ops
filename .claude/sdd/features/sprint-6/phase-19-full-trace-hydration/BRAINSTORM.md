# BRAINSTORM: phase-19-full-trace-hydration — Re-run + Hydrate the Full Trace

**Sprint/Phase:** sprint-6/phase-19-full-trace-hydration | **Date:** 2026-06-02

---

## Problem Statement

Phases 17 and 18 established the data contracts for a fully legible trace — question and
answer on spans (Phase 17), verdict lists in gold (Phase 18), bronze archive ratified in
ADR-0010. Phase 19 must close the sprint: build the bronze writer, re-run the eval sweep to
populate gold verdict lists + bronze payloads, hydrate verdicts onto the judge span, and
verify end-to-end that a failed trace in Phoenix tells its full story
(question → evidence → answer → judge verdict) without leaving Phoenix.

Three distinct pieces interact — sequencing and scoping them correctly is the central
design decision.

---

## Suggested Research & KB Work

| Topic                                                                                                                                     | Coverage                                                                                                                                                                                                                                                                                                                                 | Action                                                                                                                                                                                                                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenInference rendering of structured data on LLM spans — `output.value` as JSON string vs. human-readable text vs. `llm.output_messages` | **Thin** — Phase 17 confirmed `input.value`/`output.value` + `mime_type` make the Info tab render plain text; the judge verdict is _structured_ (lists of label objects), not plain text. Which `mime_type` makes Phoenix's Info tab render the verdict readably?                                                                        | Resolve inline (Context7 or brief source scan of openinference-python attributes) — the answer is `application/json` + JSON-serialized string for structured data, or `text/plain` + a human-formatted string for readability. No `--deep-research`. |
| Bronze writer: thread-safe per-record flush matching the runner's `write_lock` + `ThreadPoolExecutor` model                               | **Sufficient** — `rag-eval` KB `concurrent-eval-sweep` + `stats-capture-seam`; verified in `runner.py:160–268` (per-record flush under `write_lock`). The bronze writer needs its own lock or file-per-record scheme to be safe under `--concurrency 8`.                                                                                 | None — reuse the runner's lock model.                                                                                                                                                                                                                |
| Generator/judge seam — what `*_with_stats` currently returns vs. what bronze needs                                                        | **Sufficient** — verified in `runner.py:184/187`: `generate_with_stats` / `judge_with_stats` return `(result, CallStats)`. The raw request payload (messages) and raw response object are **constructed** in each provider's implementation but not surfaced to the caller. Exposing them requires a signature change or a side-channel. | None — the seam scope question is the central approach tension; resolved in approaches below.                                                                                                                                                        |
| Eval-baseline re-run recipe (hardware constraints, no-resume, OOM risk)                                                                   | **Sufficient** — eval-baseline memory entry: `make build-index-gold` (~1–2h MPS re-embedding), `caffeinate -i -s uv run rag-eval run --config configs/baseline.yaml --concurrency 8` (~40 min), close Chrome (OOM risk), no resume on crash (runner truncates on `w` open).                                                              | None.                                                                                                                                                                                                                                                |
| Boundary enrichment pattern for opt-in bronze lookup in `exporter.py`                                                                     | **Sufficient** — Phase 16/17 precedent: `doc_lookup` / `question_lookup` injected via `cli.py` at the boundary, passed into `replay_jsonl`, post-processed in `exporter.py` after `build_span_attrs`. A `bronze_lookup` follows the exact same shape.                                                                                    | None.                                                                                                                                                                                                                                                |

Coverage is sufficient across all topics. **No `--deep-research` needed.** One light
OpenInference rendering question resolved below.

### OpenInference rendering — judge verdict format

The verdict is a list of `{fact, verdict}` / `{doc_id, verdict}` objects — structured
data. Phoenix's Info tab renders `output.value` as-is; with `mime_type = "text/plain"` it
shows a raw string, with `mime_type = "application/json"` it pretty-prints JSON. Either is
readable, but a human-formatted string (e.g. `"fact: X → present\nfact: Y → absent"`) is
more immediately legible than raw JSON array on a narrow Info panel. The `llm.output_messages`
convention is for multi-turn message arrays and adds no benefit here. **Recommendation:**
serialize the verdict lists to a compact human-readable multi-line string, set
`output.mime_type = "text/plain"`. This keeps `mime_type` consistent with the generation
span (Phase 17) and requires no Phoenix-side JSON rendering support. The mapper function
(`build_span_attrs`) can do the formatting with a pure `str.join` — no new import.

---

## Approaches Considered

| Approach                       | What gets built                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Re-run needed                                                                     | Generator/judge seam impact                                                                                                                                                                                               | Verdict hydration             | Prompt hydration                                   | Test path                                                                                                                | Effort  |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------- |
| **A — Full-fidelity**          | Bronze writer (full seam change: `generate_with_stats`/`judge_with_stats` in 3 generators + the judge must expose raw request+response) + `.gitignore` entry + `--enrich-from-bronze` CLI flag; full 500×2 re-run to re-publish baseline + populate gold+bronze; hydrate verdict from gold (mapper) AND generation prompt from bronze (boundary read via `--enrich-from-bronze`)                                                                                                                                                                                                                                                                                                                                                                        | 500×2 full sweep; ~1–2h index + ~40 min eval                                      | **High** — signature change or side-channel across OpenAI + Anthropic + Gemini generators + OpenAI judge; each provider's impl must surface the raw messages it built and the raw response object                         | Always-on, pure mapper (gold) | Opt-in, boundary read from bronze                  | Bronze correctness via stubs/cassettes; full path only via the big live run; prompts only testable with bronze populated | **L**   |
| **B — Lean sprint-goal-first** | Bronze writer built + offline-tested (stub/cassette, per ADR-0010 contract) but with NO generator/judge seam change — write the raw request as the message list the runner already sees (the assembled `ctx_chunks + question` that _arrives_ at `generate_with_stats`, not reconstructed from bronze); `.gitignore` entry; verdict hydrated from gold (pure mapper, no re-run needed for the code); small representative re-run (~20–50 q, both models, targeting known failure cases) to populate gold verdict lists; no `--enrich-from-bronze` (generation-prompt hydration deferred); verify the legible trace in Phoenix                                                                                                                           | ~20–50 q small live run; ~10 min (index already built if not stale) + ~5 min eval | **Minimal** — no seam change to generators/judge; the bronze writer records what the runner passes in, not what the provider SDKs build internally                                                                        | Always-on, pure mapper (gold) | **Deferred** — Won't this phase                    | Bronze correctness offline (stubs); judge verdict hydration testable offline; small live run verifies end-to-end         | **S–M** |
| **C — Hybrid/middle**          | Bronze writer with a **bounded seam change** — extend `*_with_stats` to also return the request messages list (the `list[dict]` the provider already builds, exposed cheaply) but NOT the raw response object (the response is already parsed into `AnswerWithSources` / `JudgeVerdict`); write bronze as `{request_messages, answer_json, verdict_json}` (derived objects, not the SDK response blob); `.gitignore` entry + `--enrich-from-bronze` CLI flag; small live run (~20–50 q) populating BOTH gold verdicts + bronze; hydrate verdict from gold (mapper) AND generation prompt from bronze (boundary read); verify the fully legible trace end-to-end on the small run; defer re-publishing the full 500-q baseline to a separate optional op | ~20–50 q small live run                                                           | **Medium** — `generate_with_stats`/`judge_with_stats` return a third value (request messages list); 3 generators + 1 judge updated, each in ≤5 lines; CallStats stays unchanged; runner call sites update their unpacking | Always-on, pure mapper (gold) | Opt-in, boundary read from bronze (small live run) | Bronze correctness offline; end-to-end proof on ~20–50 q; no full sweep needed to demonstrate all code paths             | **M**   |

---

## Recommended Approach

**Approach B — lean sprint-goal-first**, with one clarification: the bronze writer IS
built and offline-tested here (it is the ADR-0010 obligation Phase 18 deferred), but the
**generation-prompt hydration** onto Phoenix spans is explicitly a Won't — it is deferred
beyond this sprint.

Rationale:

1. **The sprint goal is "a failed trace explains itself" — question + evidence + answer +
   judge verdict.** Phase 17 delivered question + evidence + answer. Phase 18 put the verdict
   lists in gold. Phase 19's unique contribution is (a) building the bronze writer per
   ADR-0010 and (b) hydrating the verdict onto the judge span. "Generation input prompt" does
   not appear in the sprint goal's ordering (question → evidence → answer → judge verdict) —
   it is an additional enrichment that Phase 17's Won't list explicitly deferred.

2. **The generator/judge seam change is a disproportionate cost for this sprint's evidence.**
   The sprint already has the answer on the generation span (`output.value`, Phase 17) and the
   evidence on the retriever span (Phase 16). The _input_ prompt to generation adds no new
   diagnostic signal for the "failed trace explains itself" criterion — a reviewer already sees
   _what was retrieved_ (evidence) and _what was answered_; seeing the verbatim assembled prompt
   (which embeds those same chunks) is a nice-to-have. It touches 3 generators + 1 judge across
   provider-specific paths where a signature change introduces regression risk.

3. **The small representative re-run is the right verification surface for a closed sprint.**
   The sprint goal is verified by demonstrating one fully-legible failed trace end-to-end in
   Phoenix. A 20–50 question run across both models, designed to include a known-failing
   category (e.g. `info_not_found` abstention failure or a `conflicting_info` case), achieves
   that verification at a fraction of the cost and with no OOM risk. A full 500×2 re-published
   baseline is a separate, optional activity after the sprint closes — the no-re-runs guard
   discourages running it again speculatively.

4. **The bronze writer built-but-not-wired-for-prompt is still a complete ADR-0010
   deliverable.** ADR-0010's contract for the writer (key scheme, idempotency,
   opt-in flag, thread safety, `.gitignore`) is fully satisfiable without the generator seam
   change. Bronze captures what the runner has in scope at the build site — including the
   question, the assembled context (ctx*chunks), the answer, and the verdict. The raw \_API
   request messages* are what the seam change exposes; without it, bronze is slightly less rich
   but still useful for debugging and future fields. The B2-fallback recorded in ADR-0010
   (verdicts in gold, no bronze) is avoided — we do build bronze, just without raw API
   request capture from inside the provider implementations.

5. **Verdict hydration from gold is always-on and zero-cost (no seam, no re-run needed for
   the code path).** `record.per_fact` / `record.per_citation` are now in gold. The mapper
   (`build_span_attrs`) sets `judge_attrs["output.value"]` from them with a pure `str.join`
   — the exact shape Phase 17 used for `gen_attrs["output.value"] = record.answer`. This is
   the highest-value line in the phase and it costs zero architecture work.

Implementation shape (for `/define` to ratify):

- `observability/attributes.py`: in `build_span_attrs`, add `output.value` (formatted
  multi-line string from `record.per_fact` + `record.per_citation`) and
  `output.mime_type = "text/plain"` to `judge_attrs`. Guard: if both lists are `None` or
  empty, omit (same cost-omit pattern as `cost_usd`). No new import.
- `eval/bronze.py` (new, small): `BronzeWriter` class — `write(run_id, question_id, model,
call_type, payload_dict)` where `payload_dict` is the caller-assembled dict (question,
  context chunks, answer/verdict as derived objects). Thread-safe (its own lock per
  `run_id`), per-record flush (`json.dump` + `f.flush()`), overwrite-by-key (path-based
  key → always overwrite). `run_id` sanitized: reject or replace `/` in `run_id` with `_`
  (ADR-0010 obligation).
- `eval/runner.py`: when `persist_bronze=True` (from `RunConfig`), after step 5 (EvalRecord
  built), call `bronze_writer.write(...)` with the question text, context chunks (already in
  scope as `ctx_chunks`), the answer object, and the verdict object. This does NOT require
  any generator/judge seam change — everything needed is already in scope at `runner.py:227+`.
- `eval/config.py` (or `RunConfig`): add `persist_bronze: bool = False` opt-in field (per
  ADR-0010 default-off).
- `.gitignore`: add `data/raw_eval/` (ADR-0010 obligation).
- `observability/cli.py`: no new flag this phase (generation-prompt `--enrich-from-bronze`
  deferred).
- Tests: `tests/eval/test_bronze.py` (new) — offline stubs; `tests/observability/
test_attributes.py` (extend) — verdict formatting in `build_span_attrs`.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | `build_span_attrs` maps `record.per_fact` + `record.per_citation` → `judge_attrs["output.value"]` (human-readable multi-line string) + `output.mime_type = "text/plain"` — always-on, no new import, in-record data (mirrors Phase 17's answer mapping)                                                                                                                                                                                                                                |
| **Must**   | Guard: omit `output.value` on judge span when both verdict lists are `None` or empty (abstention path; same cost-omit pattern as `cost_usd`)                                                                                                                                                                                                                                                                                                                                           |
| **Must**   | `eval/bronze.py` — new `BronzeWriter` module matching the ADR-0010 contract: key scheme `data/raw_eval/{run_id}/{question_id}__{model}__{gen\|judge}.json`, overwrite-by-key idempotency, thread-safe (lock per writer instance), per-record flush, `run_id` sanitized (no `/` in path segment)                                                                                                                                                                                        |
| **Must**   | `eval/config.py` / `RunConfig`: `persist_bronze: bool = False` opt-in field (default off — ADR-0010 obligation)                                                                                                                                                                                                                                                                                                                                                                        |
| **Must**   | `eval/runner.py`: when `persist_bronze=True`, call `BronzeWriter.write(...)` after the EvalRecord is built, with question text + ctx_chunks + answer + verdict (all in scope at `runner.py:227+` — no generator/judge seam change needed)                                                                                                                                                                                                                                              |
| **Must**   | `.gitignore`: add explicit `data/raw_eval/` entry (ADR-0010 obligation — confirmed NOT covered by existing `data/raw/` or `results/*` patterns)                                                                                                                                                                                                                                                                                                                                        |
| **Must**   | Small representative re-run (~20–50 q, both models, including ≥1 known-failure case) to populate gold `per_fact`/`per_citation` in JSONL and write bronze; uses the existing `configs/baseline.yaml` with a reduced `num_questions` or a targeted-category filter                                                                                                                                                                                                                      |
| **Must**   | Verify a fully legible failed trace in Phoenix: question text (Phase 17) → retrieved-doc content (Phase 16) → answer (Phase 17) → judge verdict reasoning (Phase 19) — all visible in the Info tab without leaving Phoenix                                                                                                                                                                                                                                                             |
| **Should** | `tests/eval/test_bronze.py` (new) — offline unit tests: key-scheme correctness, idempotency on same-key write, thread-safety (two threads writing the same `run_id`, different `question_id`s — no interleave), `run_id` with `/` rejected/sanitized, no-write when `persist_bronze=False`                                                                                                                                                                                             |
| **Should** | `tests/observability/test_attributes.py` — extend: verdict-present case (judge span carries `output.value` with correct label strings), verdict-absent case (both lists `None` → no `output.value` key), verdict-empty case (empty lists → consistent behavior with absent case)                                                                                                                                                                                                       |
| **Should** | `make lint test` passes; bronze-related tests run offline (no live LLM, no network)                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Could**  | `--enrich-from-bronze` CLI flag on `rag-export-traces` and supporting `bronze_lookup` param on `replay_jsonl` / `exporter.py` — would allow generation-prompt hydration from bronze onto the generation span's `input.value`; deferred because it requires the generation-prompt to be in the bronze payload, which needs the generator seam change (Approach C/A) — only implement if the generator seam change is judged in-scope by `/define`                                       |
| **Could**  | Generator/judge seam change: extend `generate_with_stats`/`judge_with_stats` to return `(result, CallStats, request_messages)` so bronze captures the actual API request payload (not the derived objects); adds raw request richness to bronze but requires updating 3 generators + 1 judge + 1 call site in `runner.py`; strictly a nice-to-have given the sprint goal is already met without it                                                                                     |
| **Could**  | Full 500×2 re-run (re-publish baseline) with bronze populated — a separate optional invocation after the sprint closes; not needed to verify the sprint goal                                                                                                                                                                                                                                                                                                                           |
| **Won't**  | **Generation-prompt hydration onto the generation span's `input.value`** — the generation input (the assembled prompt embedding k=10 context chunks) is NOT persisted in gold, and without the generator seam change it is not in bronze either; hydrating it would require Approach C or A; the sprint goal "question → evidence → answer → verdict" does not name the generation prompt as a required element, and the evidence is already visible via the retriever span (Phase 16) |
| **Won't**  | Generator/judge seam change this phase (i.e., making it a Must) — the `*_with_stats` signature change across 3 generators + 1 judge is a non-trivial refactor that introduces regression risk and is not required to close the sprint goal; if it surfaces as a need, it belongs in a new phase                                                                                                                                                                                        |
| **Won't**  | Re-publishing the full 500×2 baseline as part of this phase — a small run (~20–50 q) is sufficient to verify the sprint goal; the full re-run costs significant time + compute with no new diagnostic value for the sprint close                                                                                                                                                                                                                                                       |
| **Won't**  | Any new KB update this phase — the `rag-eval` and `observability` KB refreshes (for `per_fact`/`per_citation` fields + bronze + verdict hydration) are deferred to after the sprint closes and the sprint-6 `/update-kb` run                                                                                                                                                                                                                                                           |
| **Won't**  | Any `EvalRecord` schema change — Phase 18 shipped the new fields; this phase only consumes them                                                                                                                                                                                                                                                                                                                                                                                        |
| **Won't**  | Any dashboard change — this phase is Phoenix-only (per-trace drill-down); the dashboard is aggregate and unchanged                                                                                                                                                                                                                                                                                                                                                                     |

---

## Open Questions

1. **Bronze payload: derived objects or raw strings?** Without the generator seam change,
   the bronze writer captures `ctx_chunks` (a `list[Chunk]` from `ContextAssembler`) and the
   validated `AnswerWithSources` / `JudgeVerdict` objects — serialized to JSON. This is _derived_
   data (the prompt is reconstructable from the chunks; the answer/verdict are parsed from the
   raw response). Is this sufficient for ADR-0010's intent ("full raw payload"), or does ADR-0010
   strictly require the raw API request/response objects (which needs the seam change)? If the
   latter, the B2-fallback (verdicts in gold only, no bronze at all) may be the cleaner choice.
   `/define` should ratify which interpretation of ADR-0010 is in-scope.

2. **Judge span `output.value` format: multi-line human-readable vs. JSON?** The recommendation
   is a `text/plain` formatted string (e.g. `"fact: X → present\nfact: Y → absent"`). The
   alternative is `json.dumps([{"fact":…,"verdict":…}, …])` with `mime_type = "application/json"`.
   Which is more legible in Phoenix's actual Info tab given the sprint goal ("a failed trace
   explains itself")? This needs to be seen in practice — `/define` should specify the format
   so the test can assert exact string shape.

3. **Small re-run: how small, and which questions?** The sprint goal requires "≥1 known-failure
   case" visible in Phoenix. Options: (a) run all 500 but stop at `cost_ceiling_usd` after ~20–50
   questions (the runner already supports this and produces a valid JSONL); (b) use a targeted
   subset config (`category: info_not_found`, ~50 questions). The `cost_ceiling_usd` approach
   is simpler (no config change) but the failure case is left to chance. The category-filter
   approach guarantees a legible failure but requires a config addition. Which does `/define`
   prefer?

4. **`run_id` sanitization: reject or replace?** ADR-0010 says "sanitize `run_id` so it cannot
   contain path separators." Two options: (a) raise `ValueError` at `BronzeWriter.__init__` if
   `run_id` contains `/` or `..` — strict and loud; (b) replace `/` with `_` — silent but
   prevents the foot-gun. The runner currently generates `run_id` as a timestamp slug (no `/`
   in practice), so this is a defensive guard, not a real runtime path. Which is cleaner for
   the error model?

5. **`build_span_attrs` verdict guard: `None` vs. empty list.** When `record.per_fact` is
   `None` (old record pre-Phase-18, or a future code path that skips the judge), omit
   `output.value` — correct. When `record.per_fact` is `[]` (a legitimate abstention verdict
   with zero facts scored), should `output.value` show an empty string / "no verdicts", or
   be omitted? The `cost_usd` precedent omits when `None` — it has no empty-list case. The
   answer affects what the Info tab shows for abstention traces, which may be the most common
   failure case. `/define` should decide: emit a minimal `"(no facts scored)"` string, or
   omit entirely when the list is empty.

---

## Next Step

-> `/define sprint-6/phase-19-full-trace-hydration`

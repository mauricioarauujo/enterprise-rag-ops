# Review: sprint-2/phase-4-perfact-judge — Per-Fact LLM-as-Judge

**Branch:** `sprint-2/phase-4-perfact-judge` | **Date:** 2026-05-23 | **Verdict:** ✅ READY

## Summary

A clean, well-scoped per-fact judge that faithfully mirrors the Sprint 1 generation
layer's proven shape: a `Judge` Protocol seam, an `OpenAIJudge` (single strict
structured-output call) and CI-safe `StubJudge`, pure-Python aggregation, and a typed
`questions` loader. All 15 acceptance criteria are met (AC-12, the vcrpy cassette, is
Should-tier and intentionally not landed). `make test` is green and the offline-CI
invariant holds — `openai` is imported only in `openai_judge.py`. Five non-blocking
improvements were found and **all five were fixed in the same session** (test count
143 → 151); none ever blocked the PR.

## Mechanical Checks

| Step   | Status | Notes                                                  |
| ------ | ------ | ------------------------------------------------------ |
| Format | PASS   | `ruff format --check` — 74 files already formatted     |
| Lint   | PASS   | `ruff check` + prettier — all checks passed            |
| Tests  | PASS   | 151 passed, 17 deselected (`not corpus and not smoke`) |

Dependency hygiene confirmed: `pyproject.toml`/`uv.lock` unchanged (0 new deps — vcrpy
declined per ADR), `__pycache__` is gitignored.

## Issues

> **All five resolved in-session** (2026-05-23). Each `<details>` records the original
> finding; the **Resolution** line under it points to the fix.

<details>
<summary>✅ Multi-chunk doc collision: last chunk silently wins — <code>openai_judge.py:63</code></summary>

`doc_text = {c.doc_id: c.text for c in retrieved_docs}` keeps only the **last** chunk's
text when several `Chunk`s share a `doc_id` (the normal chunker output). The live judge
then verifies faithfulness against a partial view of the doc — a claim supported by an
earlier chunk can be falsely marked `unsupported`. Doesn't affect `StubJudge` or the
current tests (single-chunk fixtures), so non-blocking, but it's a real correctness gap
for the production path.

**Fix:** group-and-join chunk texts by `doc_id` before resolving:

```python
from collections import defaultdict
doc_chunks: dict[str, list[str]] = defaultdict(list)
for c in retrieved_docs:
    doc_chunks[c.doc_id].append(c.text)
doc_text = {doc_id: "\n\n".join(texts) for doc_id, texts in doc_chunks.items()}
```

Add a two-chunks-same-`doc_id` test to `test_openai_judge.py`.

**Resolution:** `openai_judge.py` now groups chunks by `doc_id` with `defaultdict(list)`
and joins their texts (`\n\n`) in retrieval order. Covered by
`test_multiple_chunks_same_doc_are_joined_in_prompt`.

</details>

<details>
<summary>✅ Missing <code>tests/eval/test_prompt.py</code> mirror — convention gap</summary>

CLAUDE.md: "New module → new test file." `generation/prompt.py` has a direct
`test_prompt.py`; `eval/prompt.py` is only tested indirectly through the fake-client
path. The byte-identical-determinism (NFR-2) and schema-embedding invariants have no
direct test. **Fix:** add `tests/eval/test_prompt.py` asserting (a) `build_judge_system_prompt()`
is byte-identical across calls, (b) it embeds the `_LLMJudgeVerdict` schema (contains
`per_fact`/`per_citation`, not `fact_recall`), (c) empty `cited_docs` doesn't raise.

**Resolution:** added `tests/eval/test_prompt.py` (6 tests) — determinism, embedded
LLM-facing schema (asserts `fact_recall`/`faithfulness_ratio` absent), numbered-fact +
per-`doc_id` block rendering, the `(text unavailable)` fallback, and the empty
facts/docs case.

</details>

<details>
<summary>✅ NFR-7 missing-key guard is untested — <code>openai_judge.py:42-48</code></summary>

The clean-error guard mirrors `OpenAIGenerator`, whose guard is tested in
`test_cli.py`. The eval layer has no CLI, but the guard can be hit directly. **Fix:**

```python
def test_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAIJudge()
```

**Resolution:** added `test_missing_api_key_raises_runtime_error` to
`test_openai_judge.py`.

</details>

<details>
<summary>✅ End-to-end float test skips <code>fact_precision</code> — <code>test_openai_judge.py:108-116</code></summary>

The canned payload (`present, absent`, no `contradicted`) gives `fact_precision = 1.0`,
but the test asserts only `fact_recall` and `faithfulness_ratio`. The formula is fully
covered in `test_aggregate.py`, so this is a small end-to-end gap. **Fix:** add
`assert verdict.fact_precision == 1.0` (ideally with a `contradicted` verdict in the
payload so the assertion is non-trivial).

**Resolution:** the test now builds its own present/present/contradicted +
supported/unsupported payload and asserts all three floats (`recall = 2/3`,
`precision = 2/3`, `faithfulness = 0.5`) — the `contradicted` branch is exercised
end-to-end.

</details>

<details>
<summary>✅ Strict-compat test under-asserts nested <code>required</code> — <code>test_schema.py:66-74</code></summary>

The loop checks `"verdict" in defn["required"]` but not the other field per model. Both
are correct today, but a future field added with a default would slip the
every-property-required `strict` invariant. **Fix:** tighten to
`assert set(defn["required"]) == set(defn["properties"])`.

**Resolution:** applied — `test_schema.py` now asserts
`set(defn["required"]) == set(defn["properties"])` for every nested def.

</details>

## Acceptance Criteria

| #   | Criterion                                             | Status | Note                                                            |
| --- | ----------------------------------------------------- | ------ | --------------------------------------------------------------- |
| 1   | `FactVerdict` closed, Literal vocab                   | ✅     | `test_schema.py`                                                |
| 2   | `CitationVerdict` closed, Literal vocab               | ✅     | `test_schema.py`                                                |
| 3   | `JudgeVerdict` + LLM-facing schema strict-consumable  | ✅     | Refined to private `_LLMJudgeVerdict` (per DESIGN/ADR) — better |
| 4   | Aggregation formulas + empty-denom, no I/O            | ✅     | `None` convention; `test_aggregate.py`                          |
| 5   | `Judge` Protocol; both impls satisfy                  | ✅     | `test_judge_contract.py`                                        |
| 6   | One strict call, `RAG_JUDGE_MODEL`, re-validation     | ✅     | `test_openai_judge.py` (fake client)                            |
| 7   | Prompt: checklist + per-`doc_id` blocks               | ✅     | `test_openai_judge.py`                                          |
| 8   | `StubJudge` all-present/supported, no key/net         | ✅     | `test_judge_contract.py`                                        |
| 9   | `Question` loader: 5 fields, limit/ids, no cat filter | ✅     | `test_questions_loader.py`                                      |
| 10  | Offline tests under `make test`, no key               | ✅     | 143 passed, no network                                          |
| 11  | Anchor case: `unsupported` + faithfulness < 1.0       | ✅     | `test_judge_anchor.py` (two offline proofs)                     |
| 12  | vcrpy cassette (Should-tier)                          | ⏭️     | Intentionally not landed — declined per ADR; absence is allowed |
| 13  | Corpus-coverage caveat stated, no warning field       | ✅     | In DEFINE + test docstrings                                     |
| 14  | ADR-0001 rewritten (3-way + custom + rejections)      | ✅     | `docs/adr/0001-eval-framework.md` accepted                      |
| 15  | ≤1 new dev dep, 0 runtime dep, verify green           | ✅     | 0 new deps                                                      |

## Knowledge Capture Suggestions

This phase decided several reusable LLM-as-judge techniques that no KB domain records yet
(the `rag-eval` domain is planned but does not exist — `_index.yaml` lists only
`rag-retrieval`). The ADR itself flags this as a planned post-ADR `/new-kb`.

| What was learned                                                                                         | Suggested KB domain | Action             |
| -------------------------------------------------------------------------------------------------------- | ------------------- | ------------------ |
| Per-`doc_id` prompt isolation (one named block per cited doc) as the faithfulness discriminator          | `rag-eval`          | `/new-kb rag-eval` |
| `None` empty-denominator convention for eval ratios (N/A ≠ 0.0/1.0); abstention → `(None, None, None)`   | `rag-eval`          | `/new-kb rag-eval` |
| Schema-as-SSoT with a private LLM-facing subset to keep Python-derived floats out of the `strict` schema | `rag-eval`          | `/new-kb rag-eval` |
| Single strict structured-output call + discrete `Literal` vocab in place of majority-vote-over-N         | `rag-eval`          | `/new-kb rag-eval` |

## KB Staleness

None. The changed files live under `src/enterprise_rag_ops/eval/`, which maps to no
existing KB domain. `rag-retrieval`'s `retrieval-eval-metrics` concept covers retrieval
scoring (Phase 5), which this phase does not touch — no API/enum/constraint it documents
changed.

## ADR

No missing ADR. ADR-0001 was rewritten this phase (`deferred` → `accepted`) with the
RAGAs/DeepEval/custom matrix, the custom decision, the LangChain/litellm rejection, and
consequences (AC-14). ADR-0005 (cross-family judge) is correctly named as the **future**
swap behind the `Judge` seam, not a decision made here.

## Suggested Next Steps

1. ~~Pre-PR polish~~ — **done.** All five `⚠️` items fixed in-session (see Issues);
   `make test` green at 151 passed.
2. **Commit & open the PR** — all work is currently uncommitted on the phase branch.
   Squash the eval tree + ADR + harness-command edits into a `feat:` commit.
3. **`/new-kb rag-eval`** — seed the new domain from the four techniques above (the ADR
   sequences this as a planned post-ADR step).
4. Continue Sprint 2: Phase 5 (retrieval metrics / gold-aware corpus sampling) and
   Phase 6 (multi-model runner + report), which consume `JudgeVerdict` and the loader.

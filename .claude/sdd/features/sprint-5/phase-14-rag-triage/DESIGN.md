# DESIGN: sprint-5/phase-14-rag-triage — rag-triage Core

**Sprint/Phase:** sprint-5/phase-14-rag-triage | **Date:** 2026-06-01
**Approach:** B (BRAINSTORM) — new `eval/triage.py` pure core + thin `eval/triage_cli.py`.

## Architecture

Phase 14 is a pure, read-only groupby-aggregate over an already-classified JSONL. It
adds **no** new schema, network, or LLM. Data flow:

```
results/<classified>.jsonl          gold (HF stream @ DATASET_REVISION)
        │ EvalRecord.model_validate_json        │ load_questions(revision=…)
        ▼ (per non-blank line)                  ▼ {q.question_id: q}  (dict[str, Question])
   list[EvalRecord] ───────────────┐    ┌──── dict[str, Question]
                                    ▼    ▼
                      compute_triage(records, gold) -> TriageReport     [triage.py — PURE]
                                    │
                                    ├─ fail-fast: any record.failure_mode is None → ValueError
                                    ├─ group by (record.failure_mode, record.category)
                                    ├─ per cluster: count, rate=count/total, models_seen,
                                    │   representative (min question_id) + gold text
                                    └─ sort clusters: count desc, then (fm, cat) asc
                                    ▼
                              TriageReport (frozen dataclass)
                                    │ _report_to_dict()  (deterministic dict, FR-13)
                                    ▼
        ┌───────────────────────────┴───────────────────────────┐
        ▼ json.dumps(..., indent=2, sort_keys=False)             ▼ stdout summary table
   atomic write results/triage.json                        (clusters sorted, dominant
   (tempfile in output dir + os.replace, cleanup on fail)   called out)   [triage_cli.py]
```

`triage.py` is the **pure core** (zero I/O / network / LLM, no input mutation, mirrors
the `inspect_cli.py` dataclass+pure-function shape). `triage_cli.py` is the **thin CLI**
that does all I/O: JSONL load, gold load, atomic write, stdout — mirroring
`classify_cli.py` (argparse house pattern, `--dry-run`, temp-file + `os.replace` atomic
write with cleanup-on-failure).

### Confirmed accessors (verified from source — do not re-derive)

| Need               | Exact path                                                                   | Source                                                                 |
| ------------------ | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Model string       | `record.gen_ai.request.model` (`str`)                                        | `records.py` `GenAiFields.request: GenAiRequest`, `GenAiRequest.model` |
| Failure mode       | `record.failure_mode` (`str \| None`, default `None`)                        | `records.py` line 95                                                   |
| Category           | `record.category` (`str`)                                                    | `records.py` line 81                                                   |
| Question id        | `record.question_id` (`str`)                                                 | `records.py` line 80                                                   |
| Gold question text | `gold[qid].question` (`str`)                                                 | `questions.py` `Question.question`                                     |
| Gold dict build    | `{q.question_id: q for q in load_questions(revision=…)}`                     | as in `classify_cli.py` line 72                                        |
| Dataset revision   | `config.DATASET_REVISION` via `from enterprise_rag_ops.ingest import config` | `classify_cli.py` lines 21, 49                                         |
| Record load        | `EvalRecord.model_validate_json(stripped)` per non-blank line                | `classify_cli.py` line 84                                              |

### Dataclass shapes (frozen, slots — mirroring `InspectResult`/`ModelInspection`)

```python
SCHEMA_VERSION = "1.0"  # module-level literal (FR-13/NFR-7); Phase 15 asserts against it

@dataclass(frozen=True, slots=True)
class TriageCluster:
    failure_mode: str
    category: str
    count: int
    rate: float
    representative_question_id: str
    representative_question_text: str
    models_seen: list[str]            # sorted unique gen_ai.request.model in this cluster

@dataclass(frozen=True, slots=True)
class TriageReport:
    schema_version: str               # == SCHEMA_VERSION
    total_records: int
    models_seen: list[str]            # sorted unique across ALL records
    dominant_cluster: TriageCluster | None   # clusters[0], or None when empty
    clusters: list[TriageCluster]
```

### Serialization approach (FR-13 — deterministic bytes)

`compute_triage` already returns clusters in a fully determined order (FR-6 sort), and
all list fields (`models_seen`) are pre-sorted, so the report is order-deterministic
before serialization. `triage_cli.py` (or a small pure `_report_to_dict(report)` helper
co-located in `triage.py`) converts it to a plain `dict` with a **fixed key order**
(the dataclass field order above) and dumps via `json.dumps(d, indent=2)` with
`sort_keys=False` (the explicit dict order is the SSoT; floats render identically run to
run). No reliance on dict/set iteration order anywhere in the pipeline — grouping uses a
`dict` keyed by the `(failure_mode, category)` tuple, but the **output** order is the
post-sort list, not the insertion order. Result: byte-identical `triage.json` for the
same input (AC-13).

## File Manifest

| File                                                       | Change                 | Owner  | Phase order             |
| ---------------------------------------------------------- | ---------------------- | ------ | ----------------------- |
| `src/enterprise_rag_ops/eval/triage.py`                    | new                    | direct | 3 — core logic          |
| `pyproject.toml` (`[project.scripts]` append `rag-triage`) | edit                   | direct | 4 — config/registration |
| `src/enterprise_rag_ops/eval/triage_cli.py`                | new                    | direct | 5 — CLI wiring          |
| `tests/eval/test_triage.py`                                | new                    | direct | 6 — tests               |
| `tests/eval/__init__.py`                                   | **exists — no change** | —      | n/a                     |

Notes:

- `tests/eval/__init__.py` **already exists** (confirmed) — do not re-create. Place the
  new test as `tests/eval/test_triage.py` (package-mirroring convention satisfied).
- There is **no triage specialist** in `.claude/agents/` (only `kb-architect`,
  `code-reviewer`, and the workflow agents). Every entry is `direct`, per the SDD.
- No new schema-module phase (1) and no observability hook (5b) — this phase consumes the
  existing `EvalRecord`/`FailureMode`/`Question` schemas read-only and emits one JSON
  artifact; the phase-ordering convention's data-schema and observability rows are N/A.

## Implementation Phases

Ordered per the convention: core (`src/`) → config (pyproject) → CLI → tests.

### Phase order 3 — `src/enterprise_rag_ops/eval/triage.py` (pure core)

Module constant: `SCHEMA_VERSION = "1.0"`.

Frozen dataclasses `TriageCluster`, `TriageReport` (fields exactly as above).

`def compute_triage(records: list[EvalRecord], gold: dict[str, Question]) -> TriageReport:`

- **Fail-fast (FR-9 / AC-9):** iterate records in order; on the first `r.failure_mode is
None`, `raise ValueError(f"Record {r.question_id!r} is unclassified (failure_mode is None); run rag-classify first.")`.
- **Empty (FR-5 / AC-4):** `total = len(records)`; if `total == 0`, return
  `TriageReport(SCHEMA_VERSION, 0, [], None, [])` — no division.
- **Group (FR-3 / AC-1, AC-2):** build `dict[tuple[str, str], list[EvalRecord]]` keyed by
  `(r.failure_mode, r.category)` using the **record's own** `category`.
- **Per cluster (FR-4, FR-7):**
  - `count = len(bucket)`; `rate = count / total` (AC-3).
  - `models_seen = sorted({r.gen_ai.request.model for r in bucket})` (AC-10).
  - representative: `rep = min(bucket, key=lambda r: r.question_id)` (lexicographic first;
    AC-7); `rep_id = rep.question_id`; `rep_text = gold[rep_id].question if rep_id in gold
else ""` (AC-8).
- **Sort (FR-6 / AC-5):** `clusters.sort(key=lambda c: (-c.count, c.failure_mode,
c.category))` — count desc, tiebreak `(failure_mode, category)` asc.
- **Report (FR-8):** `report_models = sorted({r.gen_ai.request.model for r in records})`;
  `dominant = clusters[0] if clusters else None` (AC-6); return `TriageReport(...)`.

Helper `def _report_to_dict(report: TriageReport) -> dict` (FR-13 / AC-13): explicit,
fixed-order dict mirroring the dataclass field order, used by the CLI serializer. Keeping
it in the pure module keeps serialization deterministic and unit-testable offline.

_Satisfies:_ FR-1..FR-9, FR-13, NFR-1, NFR-2, NFR-4, NFR-6, NFR-7. _ACs:_ 1,2,3,4,5,6,7,8,9,10,11,13.

### Phase order 4 — `pyproject.toml` registration (FR-12 / AC-16)

Append under `[project.scripts]` (alongside the existing 7 scripts):
`rag-triage = "enterprise_rag_ops.eval.triage_cli:main"`.

_Satisfies:_ FR-12. _AC:_ 16.

### Phase order 5 — `src/enterprise_rag_ops/eval/triage_cli.py` (thin CLI)

Mirror `classify_cli.py` exactly:

- `from enterprise_rag_ops.ingest import config` and import `compute_triage`,
  `_report_to_dict`, `SCHEMA_VERSION` from `.triage`; `EvalRecord`, `load_questions`.
- `_build_parser()` (argparse, `prog="rag-triage"`):
  - `--results` (required) — input classified JSONL.
  - `--output` (default `"results/triage.json"`) (FR-11; Resolved Decision §1).
  - `--dry-run` (`action="store_true"`).
  - `--questions-revision` (default `config.DATASET_REVISION`).
- `main(argv: list[str] | None = None) -> int`:
  1. `logging.basicConfig(...)`; resolve paths; if `results_path` missing →
     `FileNotFoundError`.
  2. Load gold: `gold = {q.question_id: q for q in load_questions(revision=args.questions_revision)}`.
  3. Read JSONL line-by-line (skip blanks), `EvalRecord.model_validate_json(stripped)`
     into `records: list[EvalRecord]`.
  4. `report = compute_triage(records, gold)` (lets `ValueError` from FR-9 surface to the
     `except` → stderr + return 1).
  5. Build summary text from `report` (cluster table sorted by count, `dominant_cluster`
     called out, `total_records`, `models_seen`); `print(...)` to stdout.
  6. If `args.dry_run`: print summary, write nothing, return 0 (AC-14).
  7. Else atomic write (mirror `classify_cli` lines 110–136): `output_dir.mkdir(parents=
True, exist_ok=True)`; `tempfile.NamedTemporaryFile(dir=output_dir, delete=False,
prefix=".rag-triage-tmp-", suffix=".json", ...)`; write
     `json.dumps(_report_to_dict(report), indent=2)`; on write exception unlink temp and
     re-raise; then `os.replace(temp_path, output_path)` with the same cleanup-on-failure
     guard. Return 0.
  8. Wrap the body in `try/except Exception as e: print(f"Error: {e}", file=sys.stderr);
return 1`.
- `if __name__ == "__main__": sys.exit(main())`.

_Satisfies:_ FR-10, FR-11, FR-13 (write path), NFR-1, NFR-3, NFR-4. _ACs:_ 12, 14, 16.

### Phase order 6 — `tests/eval/test_triage.py` (offline, no network/LLM)

Mirror `test_inspect_cli.py` style: build `EvalRecord`s via `EvalRecord.model_validate({...})`
and `Question`s directly; patch `enterprise_rag_ops.eval.triage_cli.load_questions` for
CLI tests (offline). Use `tmp_path` for write tests. Map ACs to tests:

| AC                                 | Test                                                                                                                                                                 |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1 cluster key / count           | records across ≥2 `(fm, cat)` pairs → one cluster each, correct counts                                                                                               |
| AC-2 record-category authoritative | record `category` ≠ gold category → clustered under record's category                                                                                                |
| AC-3 rate                          | `rate == c/N` per cluster; `sum(c.count) == N`                                                                                                                       |
| AC-4 empty input                   | `compute_triage([], gold)` → `total_records==0`, `clusters==[]`, `dominant_cluster is None`, no `ZeroDivisionError`                                                  |
| AC-5 sort + tiebreak               | equal-count clusters ordered by `(fm, cat)` asc, count desc overall                                                                                                  |
| AC-6 dominant                      | `dominant_cluster is clusters[0]`; `None` only when empty                                                                                                            |
| AC-7 representative determinism    | ids `{qst_0009,qst_0002,qst_0005}` → `representative_question_id=="qst_0002"`, text matches gold; rerun stable                                                       |
| AC-8 missing-gold rep              | rep id absent from `gold` → `representative_question_text==""`, no exception                                                                                         |
| AC-9 fail-fast                     | a record with `failure_mode=None` → `ValueError` naming first offending `question_id` (pytest.raises + match)                                                        |
| AC-10 models_seen                  | ≥2 models in one cluster → cluster `models_seen` sorted-unique; report `models_seen` sorted-unique across all                                                        |
| AC-11 schema_version               | `report.schema_version == SCHEMA_VERSION`; present in `_report_to_dict(report)`                                                                                      |
| AC-12 JSON shape + atomic          | `main(["--results", <tmp jsonl>, "--output", <tmp json>])` → file parses to documented shape; (atomic) simulate write failure → no partial output file, temp cleaned |
| AC-13 deterministic bytes          | two `_report_to_dict`+`json.dumps` passes over same input → byte-identical                                                                                           |
| AC-14 stdout summary / dry-run     | `main([..., "--dry-run"])` prints table, dominant called out, writes **no** file, exit 0                                                                             |
| AC-15 offline guarantee            | whole suite runs with `load_questions` patched / hand-built gold; no LLM client constructed (assertion: no network import path exercised)                            |
| AC-16 console script               | `main(["--help"])` raises `SystemExit(0)`; entry-point string asserted matches `pyproject.toml`                                                                      |

_Satisfies:_ NFR-5, NFR-1 (offline). _ACs:_ all 1–16 covered (each AC has ≥1 test).

## Infrastructure Gaps

All three gap layers run against `.claude/kb/_index.yaml` and `.claude/agents/`.

| Gap Type           | Area                      | Detail                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Recommendation                            |
| ------------------ | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Missing domain     | —                         | None. `rag-eval` and `observability` both registered in `_index.yaml`; they cover every technology area Phase 14 touches (groupby-aggregate, record schema, failure taxonomy).                                                                                                                                                                                                                                                                                                                | No action                                 |
| Missing concept    | —                         | None **for Phase 14**. Needed concepts exist: `rag-eval/concepts/eval-record-schema.md`, `none-empty-denominator.md`, `retrieval-metric-aggregation.md`; `observability/concepts/failure-taxonomy.md`. The cluster→issue (idempotency) contract is **thin/undocumented** — but it is a **Phase 15** concept (lands after ADR-0009), not a Phase-14 gap. Verified against `_index.yaml`: no `eval-triage` concept exists today, and DEFINE's dependency table correctly marks it **Deferred**. | `/update-kb rag-eval` — defer to Phase 15 |
| Missing specialist | triage / eval aggregation | None. No triage specialist exists, but none is warranted: triage is a single pure module reusing confirmed accessors. `kb-architect` (`kb_domains: []`) owns the KB domains; no `kb_domains` on any agent references an "eval-triage" domain. Manifest correctly uses `direct`.                                                                                                                                                                                                               | No action                                 |

**Verification of DEFINE's "no new KB/agent" conclusion:** confirmed. `_index.yaml`
lists no `eval-triage` concept and the two named domains exist with the four cited
concepts present; `.claude/agents/` has no triage specialist and no agent claims a triage
`kb_domains`. The only thin spot (cluster→issue contract) is genuinely Phase-15-owned.

## Consistency Check

Two implementation modules (`triage.py` + `triage_cli.py`) but 16 ACs and a cross-phase
schema contract → full 6-pass check run (DEFINE↔DESIGN + constitution: AGENTS.md §
Engineering Behavior / § Conventions, the `rag-eval` + `observability` KB, ADR posture).

**Verdict: ✅ CONSISTENT** — no CRITICAL/HIGH drift; coverage complete both directions.

| ID  | Severity | Pass                   | Location                                                        | Finding                                                                                                                                                                                                                                                                                 | Suggested fix                                          |
| --- | -------- | ---------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| C1  | LOW      | Duplication            | FR-4 `models_seen` (per-cluster) vs FR-8 `models_seen` (report) | Same field name at two scopes; not a true duplicate (different denominators: cluster-subset vs all-records). DESIGN disambiguates explicitly in the dataclass shapes.                                                                                                                   | None — keep both, names are scoped by their dataclass. |
| C2  | LOW      | Ambiguity              | FR-13 "deterministic dataclass→dict dump"                       | DEFINE doesn't name the serializer; DESIGN pins it to explicit fixed-order dict + `json.dumps(indent=2, sort_keys=False)`. Resolved in DESIGN.                                                                                                                                          | None.                                                  |
| C3  | LOW      | Underspecification     | FR-11 `--output` default vs Resolved Decision §1                | Both state `results/triage.json`; consistent. Representative-text empty-string path (FR-7/AC-8) fully specified.                                                                                                                                                                        | None.                                                  |
| C4  | —        | Constitution alignment | Engineering Behavior (minimal scope, seams)                     | No speculative scope: `--group-by`, derived metrics, model-as-axis all explicitly Won't. No seam built "in case". `schema_version` is justified by a **named** future change (Phase 15 consumer), not "in case" — passes the seam test. Test mirror + atomic-write conventions honored. | None — compliant.                                      |
| C5  | —        | Coverage               | DEFINE FR/AC ↔ manifest                                         | Every FR maps to a manifest file (FR-1..9,13→triage.py; FR-10,11→triage_cli.py; FR-12→pyproject); every AC-1..16 maps to a phase + test row. No orphan requirement, no orphan manifest entry.                                                                                           | None.                                                  |
| C6  | LOW      | Inconsistency          | terminology                                                     | "cluster", "failure_mode × category", "dominant_cluster", "models_seen" used identically in DEFINE and DESIGN. No drift.                                                                                                                                                                | None.                                                  |

## Risks & Trade-offs

- **Phase-15 schema contract (`schema_version`) — the thing worth getting right.** The
  `triage.json` shape is the cross-phase contract Phase 15 drafts Issues from. Risk: a
  mid-sprint Phase-14 edit silently changes the shape. Mitigation already in design:
  `SCHEMA_VERSION = "1.0"` is a literal module constant (NFR-7), surfaced in the artifact
  (AC-11), and Phase 15 asserts against it. Keep field names/order stable; any
  breaking change bumps the version. Resolved Decision §2 (only observed clusters emitted;
  `dominant_cluster is None` on empty input) is part of this contract — Phase 15 must
  handle a never-observed mode having no row and a possibly-`None` dominant.
- **Multi-model inflation (NFR-6).** A 3-way-sweep JSONL would triple clusters if `model`
  were a groupby axis. Design keeps model strictly metadata (`models_seen`); the
  `(failure_mode, category)` key is the only grouping axis. Low risk if honored.
- **Gold-join offline fragility.** The CLI streams gold from HF (network). Tests must
  patch `load_questions` (per `test_inspect_cli.py`) so the suite stays offline (AC-15);
  the pure core never touches the network (NFR-1).
- **ADR posture.** **No ADR is warranted for Phase 14** — it adds no new architectural
  seam or tool decision; it reuses confirmed schemas and house patterns. The schema/issue
  contract decision is **ADR-0009, owned by Phase 15** (per BRAINSTORM and the DEFINE
  dependency table). Do not author an ADR here.

## Next Step

→ `/implement sprint-5/phase-14-rag-triage` — no infrastructure gaps to clear first
(KB/agent additions are Phase-15-owned). The implement stage normally runs in
**Antigravity / Gemini** against this `DESIGN.md` + `DEFINE.md` as the cross-tool
contract (see § Implement Contract in `AGENTS.md`): create `eval/triage.py`, register
`rag-triage` in `pyproject.toml`, add `eval/triage_cli.py`, then `tests/eval/test_triage.py`;
gate with `make lint test`.

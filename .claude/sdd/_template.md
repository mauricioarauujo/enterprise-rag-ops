---
# Machine-queryable frontmatter (read by check_spec_status.py).
status: draft # draft | approved | implemented | archived
governing_adrs: [] # e.g. [ADR-0007, ADR-0009] — every contract traces to ≥1 decision record
source_charters: [] # links to L0 intent (CHARTER.md). Once a CHARTER exists this is ENFORCED:
  # trace it, or set `infra: true` below to declare an ADR-born module that owns no L0 intent.
infra: false # true = ADR-born infra module, exempt from charter tracing (check_spec_status.py)
surfaces: "" # "HTTP: POST /x" | "in-graph tools" | "internal only"
ssot: [] # (set at sign-off, Rule 12) e.g. ["src/<module>/models.py", "docs/schema/<module>.md"]
sprint: "" # S-NN that implements this (optional until scheduled)
phase: "" # P-N (optional)
last_updated: "YYYY-MM-DD"
---

# SPEC: <module> — <one-line mission>

> **Template** — delete these guidance blockquotes when instantiating. Prefer copying the
> worked `EXEMPLAR-SPEC.md` over this bare template.
> **Size guardrail (per ARTIFACT, not per spec):** when executable schemas/contracts outgrow
> the narrative, become a folder — `<module>/README.md` + `data-model.md` + `contracts.md`
> (complete, copyable code). Never trim executable completeness to fit a budget — split (Rule 10).
> **Executable over prose:** schema/contract sections are code blocks the implementing agent
> copies verbatim; prose describing a schema is a smell (Rule 11).
> **Ground in repo evidence:** wherever the spec touches existing code, cite real paths/
> signatures — never assume them.

**Changes:** <one line per material change>

## 1. Purpose & boundaries

> 2–4 sentences of mission. Then the contract of scope — mandatory; agents over-implement.

- **Owns:** …
- **Does NOT own:** … (→ which module does)
- **Non-goals (v1):** explicit list of tempting-but-excluded behavior, with any _reserved
  decisions_ so a later adoption doesn't re-litigate.

## 2. Policies _(the behavior the schemas can't show — optional)_

> Lifecycle states, idempotency rules, "missing beats fake" invariants, version pinning,
> attribution — anything an agent must honor that a type signature doesn't express.

## 2.1 Non-functional requirements _(Security · Data-handling · Observability — address-or-N/A)_

> First-class, not an afterthought. State each, or mark `N/A` with one line of why (the D31
> conditional pattern). An unstated NFR is one the agent will not build.
>
> - **Security:** authn/authz model, input-validation / injection surface, secrets handling.
> - **Data-handling:** PII / data classification, retention + hard-delete, tenancy/isolation.
> - **Observability:** what is logged / measured / traced, and the signal for each §10 failure-mode AC.
>
> Each non-trivial NFR SHOULD become a §10 acceptance criterion (a runnable check) or an explicit,
> owned waiver — not a paragraph nobody tests.

## 3. Data model

> Concrete, final-shape: tables/columns/types/indexes, collection/payload schemas. Include
> ownership (which module writes), soft-delete semantics, isolation columns. Feeds your schema
> docs on implementation (Rule 4).

## 4. Contracts (API / IO)

> Typed request/response models (or OpenAPI/IDL fragment) for every surface. Error contract
> included (codes, shapes). For internal modules: the interface other modules consume. Complete
> and copyable — the implementing agent transplants these verbatim (Rule 11).

## 5. State / graph topology _(stateful or agent modules only — else "N/A")_

> State schema (typed fields + who writes each), nodes/steps with one-line responsibilities,
> edges + conditions, human-in-the-loop interrupt points. One Mermaid diagram as the derived view.

## 6. Tool schemas _(if the module exposes tools — else "N/A")_

> Per tool: name, typed args, return shape, side effects, risk/gate classification (+ why).

## 7. LLM step contracts _(if the module calls an LLM — else "N/A")_

> Per atomic LLM step (NOT the prompt text — that is task-level and eval-iterated): inputs (exact
> fields), output schema (typed), invariants ("never invents X", "only generative field is Y"),
> few-shot policy, tier/model class.

## 8. Eval / validation plan

> The machine-checkable definition of done: dataset (source, size, golden origin) for LLM
> surfaces; for deterministic modules, the unit/integration test shape. Gate thresholds, what
> blocks CI. For infra with no LLM surface: "ordinary tests derived from §10 ACs."

## 9. Dependencies & integration points

> What this module reads/writes of other modules, endpoints touched, journeys affected. Sequence
> diagram (Mermaid) for any cross-service flow.

## 10. Acceptance criteria

> Numbered, testable, each mappable to a test skeleton. **EARS form** — one `SHALL` per sentence.
> Cover happy path, failure modes, and non-goals (assert absence where cheap).
>
> ```
> AC-01 WHEN <condition/event>
>       THE SYSTEM SHALL <expected behavior> (never <the tempting wrong behavior>)
> AC-02 WHEN <failure condition>
>       THE SYSTEM SHALL <safe behavior> (no silent <bad fallback>)
> ```

## 11. Open questions → deferred to task design

> Anything legitimately decidable later, listed explicitly so the implementing task knows its
> degrees of freedom — the difference between _deliberate_ and _invisible_ underdetermination.

# Kbind adoption report — enterprise-rag-ops (branch `kbind-adopt`)

> Deliverable of `/kbind:harness-adopt` (2026-07-01): the brownfield **inventory**, what
> was **created** (add-only), and the **proposed moves** awaiting human approval.
> Nothing in §3 is moved until you approve it. **This report is transient** — archive or
> delete it once the PR merges and the §3 decisions live in their canonical homes.

Context that shaped this adoption: the repo already runs a mature **homegrown harness**
(`.claude/` with agents/commands/skills/KB/SDD, `STRUCTURE_GUIDE.md` registries, ADRs,
inert-by-default hooks) that predates kbind and shares much of its DNA. Adoption
therefore mapped heavily, created little, and pushed most overlap into §3 proposals.

## 1. Inventory (what already mapped to the conventions)

| Existing                                         | Maps to (Kbind)              | Action                                                |
| ------------------------------------------------ | ---------------------------- | ----------------------------------------------------- |
| `CLAUDE.md` (real router + orchestration)        | router                       | kept; kbind pointer section appended                  |
| `AGENTS.md` (tool-agnostic SSoT)                 | AGENTS.md twin               | kept as-is                                            |
| `docs/README.md` (documentation map)             | `docs/CONTEXT.md` docs index | kept — `layout.docs_index` override                   |
| `docs/planning/roadmap.md` (**gitignored**)      | `docs/roadmap.md` roadmap    | kept — `layout.roadmap` override (see §3d)            |
| `docs/adr/` (12 ADRs + README index)             | `docs/adrs/`                 | kept — `layout.adrs` override; `_template.md` seeded  |
| `.claude/sdd/` (SDD: BRAINSTORM/DEFINE/DESIGN)   | `docs/specs/` spec layer     | kept — `layout.specs_index` override (see §3d)        |
| `.claude/kb/` + `_index.yaml` (4 domains)        | KB + registry                | kept — already canonical location                     |
| `.claude/kb/_research/` (Deep Research zone)     | `docs/research/` dossiers    | kept — `layout.research_index` override               |
| `.claude/STRUCTURE_GUIDE.md` (registries)        | consumer registry            | kept; kbind-layer rows appended                       |
| `.claude/hooks/` (2 active + STAGED, customized) | kbind hooks                  | kept (customized — NOT overwritten); missing 4 copied |
| `.claude/settings.json` (2 hooks already wired)  | settings                     | kept as-is — repo already opted into 2 hooks          |
| `.github/workflows/ci.yml` (lint+test on PR)     | CI                           | kept; `discipline` job **appended**                   |
| `.gitignore` (CLAUDE.local.md etc. covered)      | gitignore fragment           | appended 1 missing line only                          |
| `docs/planning/backlog/` (**gitignored**)        | `docs/backlog/`              | kept — private by design, noted (no layout key)       |

Layout overrides recorded: **5** (`adrs`, `docs_index`, `roadmap`, `specs_index`,
`research_index`) — see `.claude/kbind.yaml`. No parallel default trees were created
(no-split-brain). Sanity-checked: every remapped target has real content (no bare-H1 rot).

## 2. Created (the harness layer — all new, non-destructive)

- `.claude/kbind.yaml` — conventions manifest (`v1` + `layout:` + `ci:` + conservative
  `autonomy:` L3 defaults; `target_level` is intent-only — raise it when you pick a rung).
- `.claude/sdd/CHARTER.md` — L0 charter, authored from repo signals (AGENTS.md purpose,
  ADRs). **Authored autonomously — ratify or revise via `/kbind:charter`.**
- `.claude/scripts/` — kbind deterministic cores: `kb_health.py`, `adr_trace_check.py`,
  `ac_test_check.py` + validity chain (`validity_lib.py`, `ac_green_check.py`,
  `diff_gate.py`, `red_baseline.py`, `validity_artifact.py`).
- `.claude/sdd/check_spec_status.py`, `_template.md`, `EXEMPLAR-SPEC.md` — spec-ladder
  seeds at the specs area (dormant until spec-shape convergence, §3d/§4).
- `.claude/workflows/deep-research-tiered.js` — the gather workflow.
- `.claude/hooks/` — the 4 hooks the repo's partial copy lacked: `commit-gate.sh`,
  `gate-track.sh`, `spec-gate.sh`, `README.md`. All **inert**; the repo's 2 already-wired
  hooks and its customized `STAGED.example.json` were not touched.
- `docs/adr/_template.md` — kbind ADR template at the `layout.adrs` path.
- `.claude/agents/_MIGRATION_STATUS.md` + `status: legacy` frontmatter on the 5
  pre-kbind agents (tracked debt, not deprecation — agents stay active).
- `.github/workflows/ci.yml` — **appended** `discipline` job (adr-trace blocking,
  kb-health advisory, spec-status omitted as shape-N/A).
- `.gitignore` — **appended** (`.claude/scripts/__pycache__/`), never recreated.
- This report.

Deliberately **not** created: `docs/CONTEXT.md`, `docs/roadmap.md`, `docs/specs/`,
`docs/research/` (all remapped via `layout:`), a rival CI workflow, any KB content.

## 3. Reconcile + propose (NOT applied — for approval)

**3a — Placement** — nothing found: design notes already live in the SDD layer,
decisions already live in `docs/adr/`. No scattered content to re-home.

**3b — Commands/agents/skills superseded by the plugin**

The homegrown lifecycle overlaps kbind's heavily, but the local commands are wired to
repo-specific agents (Clarity gate SSoT in `define-agent.md`, consistency self-check in
`design-agent.md`, the agy implement split). Proposals:

| Local artifact                                           | kbind equivalent                          | Proposal                                                                                                       |
| -------------------------------------------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `/sprint-start` `/sprint-close`                          | `kbind:sprint-start` `kbind:sprint-close` | **keep local** (specialized: SPRINT.md shape, KB scan, archive layout); converge later                         |
| `/brainstorm` `/define` `/design` `/implement` `/review` | `kbind:phase-*`                           | **keep local** (specialized: SDD dialect + workflow agents own the gates)                                      |
| `/implement-agy` + `agy` skill                           | — (none)                                  | genuinely unique — untouched                                                                                   |
| `/new-kb` `/update-kb` `/new-agent` `/new-command`       | `kbind:new-kb` etc.                       | **keep local** (3-pillar build + repo registries); converge when agents migrate to agentspec                   |
| `/audit-harness` (local)                                 | `kbind:audit-harness`                     | **keep both, split jobs**: local = homegrown registries/flow wiring; kbind = contract drift                    |
| `diagnose` skill                                         | `kbind:diagnose`                          | **retire local** — same origin (mattpocock MIT), same job; repoint registry                                    |
| `handoff` skill                                          | `kbind:handoff`                           | **retire local** — same job; note: local one is auto-invoked by `/review`/`/sprint-close`, repoint those first |

**3c — Duplicate-role files & orphans**

| File(s)                                             | Finding                                                                                     | Proposal                                                                       |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `.claude/hooks/STAGED.example.json` (repo copy)     | references `pre-commit-gate.sh` / `post-bash-track.sh` — **neither exists** (dangling refs) | repoint those blocks to the newly copied `commit-gate.sh` / `gate-track.sh`    |
| `docs/README.md` ↔ kbind `docs/CONTEXT.md` role     | same role, different name                                                                   | resolved via `layout.docs_index` override — no action unless you prefer rename |
| `.claude/kb/_research/` ↔ `docs/planning/research/` | two research zones (KB pillar-3 landing vs private planning notes)                          | keep both — different jobs; documented here so it isn't read as drift          |

**3d — Canonical-name normalization** (override chosen by default; rename = converge)

| Existing name                        | Canonical                  | Default (chosen)                      | Alternative                                                                                                                                                        |
| ------------------------------------ | -------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/adr/`                          | `docs/adrs/`               | `layout:` override (keep)             | rename — low value, high churn (12 ADRs + inbound links)                                                                                                           |
| `docs/README.md`                     | `docs/CONTEXT.md`          | `layout:` override (keep)             | rename — marginal portability gain                                                                                                                                 |
| `docs/planning/roadmap.md` (private) | `docs/roadmap.md` (public) | `layout:` override (keep **private**) | add a _sanitized public_ roadmap — a real decision: the private roadmap is deliberate (stranger test); only do this if you want public present-state beyond README |
| `.claude/sdd/` SDD dialect           | kbind Spec ladder          | `layout:` override (keep dialect)     | converge SDD → Spec-ladder frontmatter; unlocks `check_spec_status` + `spec-gate` + CI spec-status (largest but highest-payoff convergence)                        |

## 4. Convergence roadmap (prioritized — at your pace, never forced)

- **Tier 1 (needed for canonical conformance):**
  1. Ratify `CHARTER.md` (5-min read; it renders the direction-review question).
  2. Fix the dangling `STAGED.example.json` refs (§3c row 1).
  3. Decide the `diagnose`/`handoff` skill retirements (§3b).
- **Tier 2 (nice-to-have):** 4. Migrate the 5 legacy agents to agentspec (see `_MIGRATION_STATUS.md`). 5. SDD → Spec-ladder convergence (§3d) — then wire CI `spec-status` + the `spec-gate`
  Stop hook, and add `status:` frontmatter to future ADRs so `adr_trace_check` stops
  being vacuous. 6. Renames (`docs/adr`→`docs/adrs`, `docs/README.md`→`docs/CONTEXT.md`) — optional.
- **Deferred by decision:** autonomy `target_level` capture (owner was not in-session);
  read-only `spec-gate` wiring (blocked on Tier 2.5 anyway).

## 5. Acceptance check

- `python3 .claude/scripts/adr_trace_check.py docs/adr` → ✓ pass (**vacuous**: 0 ADRs
  parsed as accepted — repo ADRs carry `**Status**` sections, not frontmatter).
- `python3 .claude/scripts/kb_health.py` → ✗ 5 **pre-existing advisory** budget warnings
  (4 index/quick-ref overages + 1 concept at 167>150) — real KB debt, predates adoption,
  not introduced here; advisory in CI.
- `python3 .claude/sdd/check_spec_status.py .claude/sdd` → **shape-N/A** (98 "no
  frontmatter" = the SDD dialect, not rot). Not wired anywhere; dormant until §3d
  convergence.
- **Actionable findings introduced by this branch: none.**
- `main` untouched; everything on `kbind-adopt`, reviewable as one PR.

---

> **After this PR merges:** apply/decline the §3 proposals, then **archive or delete this
> file** (git history retains it) and **delete the `kbind-adopt` branch** — leaving either
> in place becomes stale SSoT duplication.

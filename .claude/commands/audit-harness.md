---
description: Read-only audit of the .claude/ harness — registries vs files, dangling refs, agent/KB binding, flow-update wiring, reachability, template conformance, budgets. --judgment for an advisory right-sizing pass.
---

# /audit-harness

A read-only health check of the orchestration harness. Surfaces where it has drifted out
of sync: registry rows without a file (and files without a row), dangling file references
in commands/agents/docs (the broken-link class that bites after a refactor), unbound or
malformed agents, KB budget/registry mismatches, whether the **flows still touch and update
the files they promise to**, **dead agents / orphan KBs** (the reachability class), **template
conformance**, and basic git hygiene.

Everything above is **mechanical** (deterministic pass/fail). For the judgment-call
questions a mechanical audit cannot answer — _is the agent roster right-sized (no missing
agent, no over-specialization)? does each agent reference the KBs/docs its role needs?_ — pass
`--judgment` for an opt-in, **advisory** LLM pass that never flips the mechanical verdict.

**Read-only.** No writes. If something is wrong, it reports + recommends the fix command
(`/new-command`, `/new-agent`, `/new-kb`, `/update-kb`) — it does not apply it.

## When to use

After any harness refactor (renames, moves, registry edits), and before opening a sprint.
It is the counterpart to the Self-Improvement Protocol (`CLAUDE.md`): the protocol _grows_
the harness, this verifies it stayed coherent.

## Output language

English (matches all harness docs — see `AGENTS.md` § Conventions).

## Inputs

None. Optional flags:

- `--terse` — single-line pass/fail summary with the failing-check count.
- `--judgment` — after the mechanical checks, run the opt-in advisory pass (see § Judgment
  mode). Reasoning-based, non-deterministic, never changes the mechanical pass/fail.

## Steps

Run each check mechanically; collect findings; print the report at the end. Treat files
under `.gitignore` (the local-only layer — `docs/planning/`, `CLAUDE.local.md`,
`.claude/cache/`, `.claude/storage/`, `.claude/worktrees/`, `.claude/settings.local.json`,
`.claude/kb/_research/inbox/`) as **expected to be absent** from the public registries —
never flag them as missing rows (the private overlay in Step 7 audits them).

1. **Registry ↔ filesystem sync** — read the registries in `.claude/STRUCTURE_GUIDE.md`
   § Registries and compare to disk (use `git ls-files` so gitignored items are excluded):
   - **Commands**: every `git ls-files .claude/commands/*.md` has a **Command Registry** row,
     and every row has a file.
   - **Agents**: every tracked `.claude/agents/*.md` (≠ `_specialist-template.md`) has an
     **Agent Registry** row, and vice-versa. (Today: `kb-architect`, `brainstorm-agent`,
     `define-agent`, `design-agent`, `code-reviewer`.)
   - **Skills**: every `.claude/skills/*/SKILL.md` has a **Skill Registry** row.
   - **KB**: every domain dir under `.claude/kb/` (≠ `_templates`, `_research`) has an entry
     in `.claude/kb/_index.yaml` `domains:` **and** a **KB Domain Registry** row; and every
     `_index.yaml` domain has a dir. (Today: `rag-generation`, `rag-eval`, `rag-retrieval`,
     `observability`.)

2. **Cross-reference integrity** (the broken-link class) — for `CLAUDE.md`, `AGENTS.md`, and
   every `*.md` under `.claude/` and `docs/`, extract repo-relative paths (backtick paths and
   `](...)` links that look like files) and verify each resolves on disk. Report every
   dangling reference as `file → missing-path`. Skip links into gitignored areas (e.g.
   `docs/planning/backlog/…`) — note them as "private target (not flagged)". Also confirm
   `CLAUDE.md` contains `@AGENTS.md` and that `AGENTS.md` exists.

3. **Agent structural integrity & KB binding** — for every agent file except
   `_specialist-template.md`:
   - **Frontmatter** carries all required keys: `name`, `description`, `tools`, `kb_domains`,
     `model` (the template's contract — `STRUCTURE_GUIDE.md` § When to add an agent).
   - **Body** has the universal **`## Mandatory Reads`** section — ERO's real KB-binding
     mechanism (flag any agent missing it). Full template-section conformance is checked
     separately in Step 7.
   - `kb_domains: []` is **allowed**: all current agents are `meta` / `workflow` /
     `code-quality` (Agent Registry `Category`), which read KB dynamically via Mandatory
     Reads, not via a static domain binding. Only a future **domain-specialist** agent
     (scaffolded from `_specialist-template.md`) should carry a non-empty `kb_domains`.
   - For any agent **with** a non-empty `kb_domains`, each value must match an `_index.yaml`
     domain (or a KB Domain Registry row marked planned/draft — note it as such).
   - Confirm `model:` is present (model routing depends on it — `STRUCTURE_GUIDE.md` §
     Agent Registry).

4. **KB health** — for each existing domain dir: required files present (`index.md`,
   `quick-reference.md`); line budgets respected against `_index.yaml` `limits` (the SSoT:
   `quick_reference ≤100`, `concept ≤150`, `pattern ≤200` — `concept`/`pattern` files live
   under `concepts/` and `patterns/`). For content depth, defer to `/update-kb` (audit mode)
   and just point to it.

5. **Flow-update wiring** — the core "do the flows touch the right files and update the
   necessary ones?" check. For each flow command, confirm the artifacts it promises to
   read/update are **reachable** (the _targets_ exist — not that they are up to date):
   - `/sprint-start` → writes `.claude/sdd/features/sprint-N/SPRINT.md`; **grooms the
     backlog** → its Steps must still reference `docs/planning/backlog/index.md` (private —
     check the _reference_ is present in the command, not the file).
   - `/sprint-close` → archives to `.claude/sdd/archive/` (dir exists); **harvests the
     backlog** → its Steps must still reference `docs/planning/backlog/index.md`.
   - `/design`, `/review` → ADRs land in `docs/adr/` (dir exists).
   - `/new-kb`, `/update-kb` → write `.claude/kb/<domain>/` + `.claude/kb/_index.yaml`
     (both exist/reachable).
     Flag a flow whose promised update-reference has **gone missing** from the command body
     (e.g. the backlog grooming/harvest step was dropped in a refactor) — that is exactly the
     "flow stopped touching its file" drift this step exists to catch. Private targets
     (`docs/planning/backlog/`, the Carreira-repo sprint track via `CLAUDE.local.md`) are
     gitignored: verify the _reference_ exists, mark the _file_ "reachable if private layer
     present" rather than missing.

6. **Orphan / reachability** (dead-weight detection — the mechanical half of "right-sized
   roster, no orphan KBs"):
   - **Dead agent** — every tracked agent (≠ `_specialist-template.md`) must be invoked by
     name in ≥1 command/flow file (`.claude/commands/*.md`, `.claude/sdd/README.md`) — its
     own file and its Agent Registry row don't count. An agent nothing invokes is dead weight
     (an over-specialization symptom) → ❌. (Today: each is referenced by the SDD commands /
     `/review` / `/new-kb` etc.)
   - **Orphan KB** — every KB domain dir must be named in ≥1 agent/command/`CLAUDE.md`/
     `AGENTS.md` beyond `_index.yaml` and its own files. A domain nothing references is likely
     dead knowledge → ⚠️ (soft: agents resolve "relevant KB domains" dynamically, so this is a
     warning to investigate, not a hard error).
   - This is the mechanical floor only. "Are we _missing_ a needed agent?" and "is this one
     redundant with that one?" are judgment calls → `--judgment`.

7. **Template conformance** — files follow their scaffold's contract. Read the templates as
   the SSoT, don't hardcode headings:
   - **Agents — universal invariants (every agent):** a `## Mandatory Reads`, a `## Quality
Gate`, and an output-spec section (`## Output Format` _or_ `## Response Format`). These
     hold across workflow/meta/specialist agents alike. Flag any missing → ❌.
   - **Agents — specialist-only:** an agent with a **non-empty `kb_domains`** (a true
     domain-specialist, scaffolded from `_specialist-template.md`) must additionally carry the
     full 5 sections from that template § Required Sections (Identity, Capabilities, Response
     Format). Do **not** assert these on workflow/meta agents — they legitimately use
     Process / Output Format instead (asserting the full 5 would false-flag them).
   - **KB — no mechanical shape check.** Beyond Step 4 (required files + line budgets), KB
     content shape is **not** mechanically enforced. The concept/pattern templates are
     starting scaffolds, not contracts — real domains use topic-appropriate headers by design
     (verified: even a `## Sources` provenance section appears in only a minority of files and
     isn't in the templates, so it is _not_ a reliable invariant). Asserting template headers
     here would false-flag the majority of files. KB structural quality is therefore a
     judgment call → `--judgment` / `/update-kb` (audit mode).

8. **Git hygiene** — nothing under a gitignored path is tracked (`git ls-files` ∩
   `.gitignore` patterns → must be empty); `.gitignore` exists; runtime dirs
   (`.claude/cache/`, `.claude/storage/`, `.claude/worktrees/`) and `settings.local.json`
   are ignored.

9. **Private overlay (if present)** — if `CLAUDE.local.md` defines an
   `## /audit-harness overlay` section, run those extra checks too and fold them into the
   report. (Where any local-only checks live, so this command stays public-safe.) If there
   is no overlay, skip silently.

## Judgment mode (`--judgment`, opt-in)

Only when `--judgment` is passed. The mechanical steps (1–9) run first and own the pass/fail
verdict; this pass is **advisory** and never flips it. It answers the questions a rule cannot:

After the mechanical report, reason over the registries, every agent file (role +
`## Mandatory Reads` + `## Capabilities`/`## Process`), `.claude/kb/_index.yaml`, and the
command set — optionally via a single isolated subagent (general-purpose, opus) so it doesn't
crowd the main context — and assess:

1. **Roster right-sizing** — _gaps:_ a specialist framing + KB-read pattern that recurs across
   commands/flows but has no agent (a `/new-agent` candidate). _Redundancy:_ two agents whose
   roles overlap enough to merge, or an agent so narrow it's over-specialized.
2. **Mandatory-Reads completeness** — for each agent, do its `## Mandatory Reads` reference the
   KB domains + docs its role actually needs? Flag an eval-touching agent that doesn't read
   `rag-eval`, an observability one that skips `observability`, etc.
3. **KB structural quality** — beyond Step 4's files + budgets: are the domains coherent,
   non-overlapping, at the right altitude, and following the template's intent (which the
   mechanical steps deliberately don't assert)? Defer deep content review to `/update-kb`
   audit mode; this is a pointer-level read.

Emit a single `## Judgment findings (advisory)` section: each finding tagged `gap` /
`redundancy` / `binding` / `kb`, with the recommended action (`/new-agent`, consolidation,
KB-binding edit, `/update-kb`). Mark the whole section **advisory — not part of the pass/fail**.

## Output (default)

```
# Harness Audit — <YYYY-MM-DD>

## Summary
- Checks: <passed>/<total> passed
- Verdict: <✅ harness is well-sealed | ⚠️ N warnings | ❌ N errors>

## Registries ↔ files
- ✅ commands: <n> files ↔ <n> rows
- ❌ agents: `foo.md` has no Agent Registry row
- ⚠️ KB: domain `bar` in _index.yaml but no KB Domain Registry row

## Cross-references
- ❌ `.claude/commands/sprint-close.md` → `docs/architecture/overview.md` (missing)
- ✅ CLAUDE.md imports @AGENTS.md

## Agent integrity & KB binding
- ❌ `code-reviewer.md` missing `## Mandatory Reads`
- ⚠️ `foo-specialist.md` declares kb_domains: [missing-domain] (no _index.yaml match)
- ✅ all other agents structurally sound (workflow agents kb_domains: [] OK)

## KB health
- ✅ / ⚠️ <per-domain line: files present, budgets ok/over>

## Flow-update wiring
- ❌ `/sprint-close` no longer references docs/planning/backlog/index.md (harvest step lost)
- ✅ /sprint-start grooming reference present; sdd/archive + docs/adr reachable

## Reachability
- ❌ `foo-agent.md` is never invoked by any command/flow (dead weight)
- ⚠️ KB domain `bar` is referenced nowhere outside _index.yaml (orphan?)

## Template conformance
- ❌ `code-reviewer.md` missing `## Quality Gate`
- ⚠️ `foo-specialist.md` (kb_domains set) missing template section `## Capabilities`
- ✅ all agents carry the universal sections; no specialists to deep-check

## Git hygiene
- ✅ no gitignored paths tracked; .gitignore present

## (overlay findings, if any)

## Judgment findings (advisory — only with --judgment, not part of pass/fail)
- [gap] recurring "X-specialist" framing across /design + /review has no agent → /new-agent
- [binding] `design-agent` Mandatory Reads omits the `observability` domain it touches

## Recommendations
1. <the fix command for each ❌/⚠️, ordered by severity>
```

Omit a section with no findings (don't print empty headers). Order findings ❌ → ⚠️ → ✅.
The judgment section appears only with `--judgment` and is always labelled advisory.

## Output (--terse)

```
Harness audit: <passed>/<total> checks ok — <✅ sealed | ❌ N errors, M warnings>. <top issue>.
```

## Notes

- Pure read. Never modify files. The fixes are other commands (`/new-*`, `/update-kb`).
- **Steps 1–9 are mechanical** (deterministic pass/fail — structural drift). `--judgment` is
  the opt-in, advisory reasoning pass for the right-sizing / coverage questions a rule cannot
  decide; it never changes the verdict.
- **Design rule — the workflow-vs-specialist trap.** A rule that is true for domain-specialist
  agents is often false for ERO's workflow/meta agents. Three checks encode this nuance rather
  than the strict rule (else they false-flag every workflow agent / KB domain): `kb_domains: []`
  is allowed (Step 3); only specialists get the full 5-section assertion (Step 7); KB files are
  not held to the template's exact headers (Step 7). When tightening a check, preserve this.
- Step 5 answers "do the flows still touch their files?" (notably the backlog grooming/harvest
  ritual in `/sprint-start` + `/sprint-close`); Steps 6–7 answer "is anything dead weight, and
  does it follow its scaffold?" — together the mechanical floor under "is the harness
  well-sealed?".
- For the content quality of a KB domain, use `/update-kb` (audit mode).

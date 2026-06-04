---
description: Read-only audit of the .claude/ harness — registries vs files, dangling refs, agent/KB binding, flow-update wiring, budgets.
---

# /audit-harness

A read-only health check of the orchestration harness. Surfaces where it has drifted out
of sync: registry rows without a file (and files without a row), dangling file references
in commands/agents/docs (the broken-link class that bites after a refactor), unbound or
malformed agents, KB budget/registry mismatches, whether the **flows still touch and update
the files they promise to**, and basic git hygiene.

**Read-only.** No writes. If something is wrong, it reports + recommends the fix command
(`/new-command`, `/new-agent`, `/new-kb`, `/update-kb`) — it does not apply it.

## When to use

After any harness refactor (renames, moves, registry edits), and before opening a sprint.
It is the counterpart to the Self-Improvement Protocol (`CLAUDE.md`): the protocol _grows_
the harness, this verifies it stayed coherent.

## Output language

English (matches all harness docs — see `AGENTS.md` § Conventions).

## Inputs

None. Optional flag:

- `--terse` — single-line pass/fail summary with the failing-check count.

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
   - **Body** has the 5 sections, and in particular a **`## Mandatory Reads`** section — this
     is ERO's real KB-binding mechanism. Flag any agent missing it.
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

6. **Git hygiene** — nothing under a gitignored path is tracked (`git ls-files` ∩
   `.gitignore` patterns → must be empty); `.gitignore` exists; runtime dirs
   (`.claude/cache/`, `.claude/storage/`, `.claude/worktrees/`) and `settings.local.json`
   are ignored.

7. **Private overlay (if present)** — if `CLAUDE.local.md` defines an
   `## /audit-harness overlay` section, run those extra checks too and fold them into the
   report. (Where any local-only checks live, so this command stays public-safe.) If there
   is no overlay, skip silently.

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

## Git hygiene
- ✅ no gitignored paths tracked; .gitignore present

## (overlay findings, if any)

## Recommendations
1. <the fix command for each ❌/⚠️, ordered by severity>
```

Omit a section with no findings (don't print empty headers). Order findings ❌ → ⚠️ → ✅.

## Output (--terse)

```
Harness audit: <passed>/<total> checks ok — <✅ sealed | ❌ N errors, M warnings>. <top issue>.
```

## Notes

- Pure read. Never modify files. The fixes are other commands (`/new-*`, `/update-kb`).
- Mechanical/rules-based by design — it catches structural drift, not judgment calls. For
  the content quality of a KB domain, use `/update-kb` (audit mode).
- Step 5 is the answer to "is the harness well-sealed?" — it verifies the flows still touch
  and update the files they promise to (notably the backlog grooming/harvest ritual wired
  into `/sprint-start` and `/sprint-close`).

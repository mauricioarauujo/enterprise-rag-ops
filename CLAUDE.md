# CLAUDE.md — Enterprise RAG Ops

Project instructions auto-loaded every turn. The **shared, tool-agnostic** source of
truth — project purpose, architecture, conventions, engineering behavior, testing, and
the cross-tool implement contract — lives in `AGENTS.md` and is imported below. This
file adds only **Claude-Code-specific orchestration** (slash commands, sub-agents,
hooks). Keep both files' edits rare and batched (a `CLAUDE.md`/`AGENTS.md` edit
invalidates the prompt cache); prefer the cache-safe `STRUCTURE_GUIDE.md` registries.

@AGENTS.md

Registries (commands, agents, KB domains) live in `.claude/STRUCTURE_GUIDE.md` — it is
not auto-loaded, so editing it is cache-safe.

---

## Quick Navigation

| What                            | Where                                           |
| ------------------------------- | ----------------------------------------------- |
| Spec / architecture             | `docs/architecture/`                            |
| Dataset notes                   | `docs/dataset.md`                               |
| Architecture decisions          | `docs/adr/` (ADR-0001–0003 shipped in Sprint 1) |
| Harness maintenance             | `.claude/STRUCTURE_GUIDE.md`                    |
| Self-improvement protocol       | `.claude/STRUCTURE_GUIDE.md` § Self-Improvement |
| Command / agent / KB registries | `.claude/STRUCTURE_GUIDE.md` § Registries       |
| KB registry (machine-readable)  | `.claude/kb/_index.yaml`                        |
| SDD layer (specs)               | `.claude/sdd/README.md`                         |

---

## Harness & SDD slash commands

A sprint is wrapped by `/sprint-start` … `/sprint-close`; each phase runs
`/brainstorm` → `/define` → `/design` → `/implement` → `/review`. Plus `/new-kb`,
`/update-kb`, `/new-agent`, `/new-command`. **Full list (the SSoT) is in
`.claude/STRUCTURE_GUIDE.md` § Registries — consult it before recommending a command.**

> Workflow split: `/brainstorm` → `/define` → `/design` → `/review` run here in Claude
> Code; the token-heavy `/implement` stage runs in Antigravity / Gemini against the
> `DESIGN.md` contract (see § Implement Contract in `AGENTS.md`).

---

## Agents

Workflow and specialist agents live flat in `.claude/agents/<name>.md`, added as
concrete needs surface (see Self-Improvement protocol). Full registry:
`.claude/STRUCTURE_GUIDE.md` § Agent Registry. Template: `_specialist-template.md`.
Scaffold with `/new-agent`. When spawning an agent, always pass `model` explicitly.

---

## Knowledge Base

KB domains are added on demand via the **3-pillar build** (codebase + MCP docs +
Gemini Deep Research) — see `.claude/STRUCTURE_GUIDE.md` § Knowledge Base. Machine
registry: `.claude/kb/_index.yaml`. Templates: `.claude/kb/_templates/`. (What the KB
is and when to read it: see § Knowledge Base in `AGENTS.md`.)

**Line budgets** are SSoT'd in `.claude/kb/_index.yaml` (`limits`).

---

## Self-Improvement Protocol (mandatory)

This harness is designed to grow. **Claude must proactively propose harness changes** when patterns emerge — don't wait to be asked.

**Trigger and suggest a harness change when any of the following holds:**

1. **Repeated reasoning** — Same domain knowledge re-derived in ≥2 sessions → propose a KB concept or pattern.
2. **Repeated workflow** — Same multi-step bash/edit sequence run ≥2 times → propose a slash command.
3. **Repeated specialist context** — Same set of files/KB reads + role framing happens ≥2 times → propose an agent.
4. **Repeated tool-usage friction** — Permission prompts on the same command pattern ≥3 times → propose adding to `.claude/settings.json`.
5. **Drift between code and KB/docs** — Code reality contradicts a documented pattern → propose an update.
6. **Missing quality gate** — A class of bug slips through twice → propose a hook or CI check.

**How to propose (don't unilaterally create):**

End the relevant turn with a `**Harness suggestion:**` block stating: (a) the trigger, (b) what to add/change, (c) where it goes, (d) one-line cost/benefit. Wait for user approval before scaffolding.

Use `/new-kb`, `/update-kb`, `/new-agent`, `/new-command` — see `.claude/STRUCTURE_GUIDE.md` for the bootstrap order.

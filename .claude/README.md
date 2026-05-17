# .claude/ — Orchestration Layer

This folder is the Claude Code orchestration system for `enterprise-rag-ops`.

**New here?** Read in this order:

1. `../CLAUDE.md` — project SSoT (auto-loaded every turn anyway)
2. `STRUCTURE_GUIDE.md` — how to add/change agents, KB, commands, skills, hooks
3. `kb/_index.yaml` — domain registry (currently empty)
4. `sdd/README.md` — Spec-Driven Development pipeline (optional, for complex tasks)

## Status

Bootstrapped in Phase 0 with **structure only**. Agents, KB domains, commands, and skills are added on demand, following the Self-Improvement Protocol in `CLAUDE.md`.

## Files you can safely edit by hand

- `settings.json` — team-shared permissions and hooks
- `kb/_index.yaml` — registry
- Any `*.md` in `agents/`, `commands/`, `skills/`, `kb/`
- `sdd/features/*` and `sdd/archive/*`

## Files NOT to edit by hand

- `kb/_templates/*.template` — scaffolding sources (copy from, don't edit)
- `hooks/*.sh` — adjust contract carefully; exit codes matter
- `cache/`, `storage/`, `hooks/.gates/` — runtime state, gitignored

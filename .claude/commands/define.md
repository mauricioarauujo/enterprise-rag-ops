---
description: SDD Phase 1 — extract requirements and pass the Clarity gate (≥12/15).
---

# /define {sprint-N/phase-slug}

Extract and validate requirements behind a single Clarity gate (SDD Phase 1).
See `.claude/sdd/README.md`.

## Arguments

`$ARGUMENTS` — the feature slug `sprint-N/phase-slug`.

## Steps

1. **Read context**
   - `.claude/sdd/features/{slug}/BRAINSTORM.md` (if it exists).
   - The sprint/phase track (Carreira repo) and relevant `docs/`.
   - Relevant KB domains from `.claude/kb/_index.yaml`.

2. **Invoke `define-agent`** — pass `model: "opus"`.
   - Extracts functional + non-functional requirements.
   - Refines acceptance criteria; analyzes dependencies.

3. **Clarity gate (≥12/15)** — 5 dimensions scored 0–3: Problem, Users, Success,
   Scope, Constraints. Below 12 → the agent asks clarifying questions and re-scores.

4. **Infrastructure readiness check**
   - Map each dependency (datasets, modules, libraries) to a KB domain and, where one
     exists, a specialist agent.
   - Flag domains/agents that are missing — recommend `/new-kb` / `/new-agent`.
   - Include the readiness table in `DEFINE.md`.

5. **Write output** → `.claude/sdd/features/{slug}/DEFINE.md`.

6. **Suggest next step** → `/design {slug}`. If gaps were found: "create/update the
   flagged KBs before designing".

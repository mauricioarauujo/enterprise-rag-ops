---
description: SDD Phase 2 — produce the architecture and file manifest.
---

# /design {sprint-N/phase-slug}

Create the technical architecture and file manifest (SDD Phase 2).
See `.claude/sdd/README.md`.

## Arguments

`$ARGUMENTS` — the feature slug `sprint-N/phase-slug`.

## Steps

1. **Read context**
   - `.claude/sdd/features/{slug}/DEFINE.md`.
   - Relevant KB domains and existing code in the affected modules.

2. **Invoke `design-agent`** — pass `model: "opus"`.
   - Maps requirements to modules across `src/` / `eval/` / `observability/`.
   - Produces a file manifest: every file → the specialist agent that owns it, or
     "direct" if no specialist exists yet.
   - Plans implementation phase ordering.

3. **Write output** → `.claude/sdd/features/{slug}/DESIGN.md`.

4. **Gap detection (deep)** — three layers, reported in `DESIGN.md`:
   - **Domain existence** — does every technology area have a KB domain in `_index.yaml`?
   - **Concept coverage** — does the domain's `concepts`/`patterns` cover this work?
   - **Agent alignment** — does each specialist's `kb_domains` include the needed domains?

   ```markdown
   ## Infrastructure Gaps

   | Gap Type           | Area     | Detail                     | Recommendation        |
   | ------------------ | -------- | -------------------------- | --------------------- |
   | Missing domain     | {tech}   | No KB exists               | `/new-kb {domain}`    |
   | Missing concept    | {domain} | Exists but lacks {concept} | `/update-kb {domain}` |
   | Missing specialist | {area}   | No agent owns these files  | `/new-agent {name}`   |
   ```

5. **Suggest next step** → `/implement {slug}`. If gaps were found, address them first.

## Phase ordering convention (RAG-eval repo)

1. Data schema / dataset loading
2. Config / settings
3. Core module logic (`src/` retrieval, generation)
4. Eval harness wiring (`eval/`)
5. Observability hooks (`observability/`)
6. Tests
7. Docs + ADR

---
description: Create or extend a KB domain via the kb-architect agent and the 3-pillar build.
---

# /new-kb {domain}

Create a knowledge-base domain (or add a concept/pattern to one) using the
`kb-architect` agent and the 3-pillar build model. See `.claude/STRUCTURE_GUIDE.md`
§ Knowledge Base for the trigger and the pillar model.

## When to use

Same domain knowledge re-derived in ≥2 sessions, **and** the area has stabilized
enough to document. Do not pre-create domains "in case".

## Arguments

`$ARGUMENTS`:

- First positional → domain slug (kebab-case).
- `--description "<one-liner>"` → purpose, used in `_index.yaml`.
- `--deep-research` → engage pillar 3 (Gemini Deep Research) for a complex topic.

## Steps

1. **Check the registry.** Read `.claude/kb/_index.yaml`. If the domain exists, ask
   whether to add a concept/pattern or stop.
2. **Pick the build path:**
   - **Simple** (default) — codebase + Context7/Exa are enough.
   - **Deep research** (`--deep-research`, or when the topic is genuinely complex) —
     run the flow in `.claude/kb/_research/README.md`: draft the Gemini prompt → review
     the returned plan → wait for the file in `_research/inbox/` → build → archive.
3. **Invoke the `kb-architect` agent** (pass `model: "sonnet"`). Brief it with: the
   domain slug, the description, the build path, and which pillars apply. The agent
   scaffolds from `_templates/`, runs the 3 pillars, curates `concepts/` + `patterns/`
   within budgets, and records agreement-analysis confidence.
4. **Verify registration.** Confirm the agent updated `_index.yaml` and added the row
   to the KB registry in `.claude/STRUCTURE_GUIDE.md` (cache-safe — not `CLAUDE.md`).
5. **CLAUDE.md.** Do **not** edit it. `CLAUDE.md` only points to the STRUCTURE_GUIDE
   registry, so no edit is needed. If one genuinely is, stage it in
   `docs/planning/claude-md-pending.md` and report it.

## Output

Report: domain, build path, pillars used, files created, budget compliance, any
agreement-analysis conflicts. If `--deep-research`, confirm the source file was moved
to `_research/archive/`.

---
description: Refresh an existing KB domain against the 3 pillars (codebase, MCP docs, research).
---

# /update-kb {domain}

Refresh a KB domain so it still matches reality, via the `kb-architect` agent. See
`.claude/STRUCTURE_GUIDE.md` § Knowledge Base.

## When to use

Code reality contradicts a documented KB pattern, or a domain's `last_updated` is stale
relative to recent `src/` / `eval/` changes (often flagged by `/review`).

## Arguments

`$ARGUMENTS` — domain slug. No argument → audit all domains.

## Steps

1. Read `.claude/kb/_index.yaml` — locate the domain entry and `last_updated`.
2. **Invoke the `kb-architect` agent** (pass `model: "sonnet"`) to re-run the 3 pillars
   against current reality:
   - Pillar 1 — grep the relevant `src/` / `eval/` / `tests/` modules for current usage.
   - Pillar 2 — Context7 for official-doc drift; Exa for newer patterns.
   - Pillar 3 — only if a research refresh is needed (see `_research/README.md`).
3. The agent diffs against existing files, updates `concepts/` / `patterns/` /
   `quick-reference`, enforces budgets (concept ≤150, pattern ≤200, quick-ref ≤100),
   and re-runs agreement analysis — flagging content the pillars now contradict.
4. The agent bumps `last_updated` in `_index.yaml`. No `CLAUDE.md` edit.
5. Report: files changed, content added/removed, conflicts found, budget compliance.

## Audit mode (no argument)

The agent scans every domain under `.claude/kb/`: required files (`index.md`,
`quick-reference.md`), budget compliance, cross-references, staleness. One health line
per domain + a recommendations list.

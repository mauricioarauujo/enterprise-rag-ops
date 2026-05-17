---
description: Refresh an existing KB domain against the codebase and official docs.
---

# /update-kb {domain}

Refresh a KB domain so it still matches reality. See `.claude/STRUCTURE_GUIDE.md`
§ Self-Improvement.

## When to use

Code reality contradicts a documented KB pattern, or a domain's `last_updated` is stale
relative to recent `src/` / `eval/` changes.

## Arguments

`$ARGUMENTS` — domain slug. No argument → audit all domains.

## Steps

1. Read `.claude/kb/_index.yaml` — locate the domain entry and `last_updated`.
2. Re-derive from source: grep the relevant `src/` / `eval/` / `tests/` modules for
   current usage.
3. Validate against official docs via Context7 when the domain covers a library; flag
   contradictions.
4. Update concepts / patterns / quick-reference. Enforce budgets (concept ≤150,
   pattern ≤200, quick-ref ≤100).
5. Bump `last_updated` in `_index.yaml`.
6. Report: files changed, content added/removed, contradictions found.

## Audit mode (no argument)

Scan every domain under `.claude/kb/`: check required files (`index.md`,
`quick-reference.md`), budget compliance, and staleness. Report a health line per domain.

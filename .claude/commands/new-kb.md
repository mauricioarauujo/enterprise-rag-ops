---
description: Scaffold a new KB domain (or a concept/pattern in an existing one) from the templates.
---

# /new-kb {domain}

Create a knowledge-base domain, or add an artifact to one. See
`.claude/STRUCTURE_GUIDE.md` § "When to add a KB concept or pattern" for the trigger.

## When to use

Same domain knowledge re-derived in ≥2 sessions. Do not pre-create domains "in case".

## Arguments

`$ARGUMENTS` — first positional is the domain slug (kebab-case). Optional
`--description "<one-liner>"`.

## Steps

1. **Check the registry.** Read `.claude/kb/_index.yaml`. If the domain exists, ask
   whether to add a concept/pattern to it or stop.
2. **Scaffold the domain** (new domain only): `cp -r .claude/kb/_templates/* .claude/kb/<domain>/`,
   then fill `index.md` from the template.
3. **Add the artifact.** Pick the type and copy its template:
   - `concepts/<name>.md` — atomic idea, ≤150 lines
   - `patterns/<name>.md` — reusable code shape, ≤200 lines
   - `quick-reference.md` — lookup table, ≤100 lines
4. **Write content** grounded in this repo — grep `src/`, `eval/`, `tests/` for real
   usage; validate library claims via Context7. Stranger test: every line teaches the
   reader about the system.
5. **Register.** Add or update the domain entry in `_index.yaml` (`status`,
   `description`, `last_updated`, `concepts`, `patterns`).
6. **Index.** Add a one-line entry in the domain's `index.md`.
7. If a new domain was created, update the Knowledge Base table in `CLAUDE.md`
   (batch with other CLAUDE.md edits).

## Output

Report: domain, files created, line-budget compliance.

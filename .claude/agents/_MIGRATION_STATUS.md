# Agent migration status — pre-kbind → agentspec

Ledger created by `/kbind:harness-adopt` (2026-07-01). These agents predate kbind and
use simple frontmatter (no agentspec KB-binding). They are **active and working** —
`status: legacy` only tells audit Tier C to skip the KB-binding check; it is tracked
debt, not deprecation. Migrate opportunistically (e.g. when an agent is next edited),
via `/kbind:new-agent` as the reference shape.

| Agent              | Current shape                          | Plan                                            |
| ------------------ | -------------------------------------- | ----------------------------------------------- |
| `brainstorm-agent` | simple frontmatter, SDD Stage 0 wiring | migrate to agentspec later (bind: sdd workflow) |
| `define-agent`     | simple frontmatter, SDD Stage 1 wiring | migrate to agentspec later (bind: sdd workflow) |
| `design-agent`     | simple frontmatter, SDD Stage 2 wiring | migrate to agentspec later (bind: sdd workflow) |
| `code-reviewer`    | simple frontmatter, `/review` wiring   | migrate to agentspec later (bind: rag-eval KB)  |
| `kb-architect`     | simple frontmatter, 3-pillar KB build  | migrate to agentspec later (bind: kb registry)  |

`_specialist-template.md` is a scaffold, not an agent — out of scope.

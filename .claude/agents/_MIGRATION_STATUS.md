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

---

## `kb-architect` — Clause-3 evidence (measured 2026-08-01)

The file now carries a `> **Override rationale:**` marker, because `override_check.py` exited 1
on it. That marker is deliberately terse (it must fit inside the checker's 40-line header
window); this is the evidence behind it.

**It is not a fork of the plugin agent — it is older than one.**

| fact                                            | measurement                                                                                                 |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| placed in this repo                             | 2026-05-17, `df45a0e` (`feat: populate .claude harness`)                                                    |
| plugin's `kb-architect` born                    | 2026-06-13, `322b6b5` — **27 days later**                                                                   |
| plugin's version's origin                       | `e2d272f` (2026-06-18) — _"de-projectified from CAAI/**ERO**/Carreira"_                                     |
| what `harness-adopt` did                        | `f461d1f` — added **one line**, `status: legacy`. It did not overwrite.                                     |
| repo-authored since adoption                    | `c08701b` (2026-07-06) — `mcp__base-aulas-aide__buscar_aulas` as a non-authoritative pillar-2 source        |
| byte-identical to any plugin blob ever shipped? | **no** — checked against all 4 (`562a8203`, `af06f59e`, `d32ba17c`, `b39f1437`) plus the workshop prototype |

So the plugin's agent descends from this one. Refreshing this file _from_ the plugin would
overwrite the ancestor with its own descendant and delete the base-aulas-aide wiring.

**Nothing here is harvestable upward.** Every section this copy has and the plugin lacks already
exists in the plugin, or was deliberately retired:

- _Line Budgets_ table → plugin `agents/kb-architect.md:82` (same numbers) + `doc_budget.py`
- _Quality Gate_ / stranger test → plugin `README.md`, `skills/audit-harness/SKILL.md`
- _Mandatory Reads_ → a template convention (`specialist-agent.md.template:46`, `new-agent`)
- _Deep Research Sub-Flow_ (manual Gemini copy-paste) → **dropped by D30**; `skill_conformance.py:40`
  names this exact case
- the base-aulas-aide block → pt-BR course MCP, project-specific, fails the stranger test

**Cost of staying on this generation.** The plugin's agent has changed **5 times** (`322b6b5`,
`a2d563e`, `e2d272f`, `ad448e9`, `5739669`); this copy received **none** of them. It predates the
D10 inline-confidence canon and the `Sources:` provenance line, and the KB it built shows it:

- **0 of 43** KB files carry an inline confidence note
- **43 of 43** carry no `Sources:` line (`kb_provenance_check.py`, report-only)

It also lacks the agentspec frontmatter (`tier`, `stop_conditions`, `escalation_rules`,
`anti_pattern_refs`), batch mode, FOLD mode, and the derived health score.

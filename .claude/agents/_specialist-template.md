# Agent Template

Use this template when creating new specialist agents for enterprise-rag-ops.

## Required Frontmatter

```yaml
---
name: { agent-name }
description: |
  {One-line description of what this agent does.}
  Use PROACTIVELY when {trigger conditions}.

  **Example 1:** {scenario}
  - user: "{example user message}"
  - assistant: "{example assistant response}"

tools: [Read, Write, Edit, Grep, Glob, Bash, TodoWrite]
kb_domains: [{ relevant-domains }]
model: { sonnet|opus }
---
```

## Required Sections

1. **Identity** — role, domain, threshold
2. **Mandatory Reads** — KB files to load before acting
3. **Capabilities** — numbered capabilities with triggers and checklists
4. **Quality Gate** — pre-flight checks before delivering output
5. **Response Format** — structured output template

## KB-First Resolution (Iterative Retrieval)

All agents follow this resolution order with progressive refinement (max 3 cycles):

1. **Broad search** — KB check (`.claude/kb/{domain}/`) + grep for relevant patterns across `src/`
2. **Evaluate** — Score relevance of findings. Do the KB patterns match the actual codebase usage?
3. **Targeted search** — Drill into specific modules using terminology learned in step 1-2
4. **MCP validation** — Context7 for library docs when KB + codebase disagree
5. **Ask user** — If confidence < threshold after refinement

## Project-Specific Checks

All code-touching agents must verify:

- New module → matching `tests/test_<module>.py` exists
- Eval-path code is not tested against a mocked LLM API — use the cassette/replay pattern
- Public docs and code comments carry no personal/career context (stranger test)
- `make verify` passes before delivering

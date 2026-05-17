---
description: Scaffold a new specialist agent from the agent template.
---

# /new-agent {name}

Create a specialist agent. See `.claude/STRUCTURE_GUIDE.md` § "When to add an agent".

## When to use

Same specialist framing + KB reads + role recurs in ≥2 sessions, AND the workflow needs
an isolated context window. Otherwise prefer a slash command.

## Arguments

`$ARGUMENTS` — first positional is the agent name (kebab-case).

## Steps

1. Confirm the trigger — second occurrence of the same framing. If not met, stop and
   suggest a slash command instead.
2. Copy the template: `cp .claude/agents/_specialist-template.md .claude/agents/<name>.md`.
3. Fill frontmatter: `name`, `description` (include "Use PROACTIVELY when …"), `tools`,
   `kb_domains`, `model`.
4. Fill the five sections: Identity, Mandatory Reads, Capabilities, Quality Gate,
   Response Format.
5. Add a row to the Agents table in `CLAUDE.md` (batch CLAUDE.md edits).

## Output

Report: agent name, file path, KB domains wired.

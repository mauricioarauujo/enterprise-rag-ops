# STRUCTURE_GUIDE.md — enterprise-rag-ops

Maintenance guide for the `.claude/` orchestration layer. Read this before adding agents, commands, KB domains, skills, or hooks.

This harness was bootstrapped in Phase 0 with **structure only** — content is added as concrete needs surface (see § Self-Improvement and the protocol in `CLAUDE.md`).

---

## Layout

```
.claude/
├── STRUCTURE_GUIDE.md     ← You are here
├── README.md              ← Orientation for new contributors / new Claude sessions
├── settings.json          ← Team-shared permissions + hooks (git-tracked)
├── settings.local.json    ← Personal permissions (gitignored)
├── agents/                ← Specialist agents (flat; empty — grow via protocol)
│   └── _specialist-template.md
├── commands/              ← Slash commands (bootstrap commands present)
├── skills/                ← Reference docs for tools (empty — grow via protocol)
├── kb/                    ← Knowledge base
│   ├── _index.yaml        ← Domain registry (machine-readable)
│   └── _templates/        ← Scaffolding templates (concept, pattern, index, …)
├── hooks/                 ← PreToolUse / PostToolUse shell scripts
│   ├── pre-commit-gate.sh
│   ├── post-bash-track.sh
│   ├── pre-bash-filter.sh
│   ├── post-compact-log.sh
│   └── .gates/            ← Flag files (gitignored)
├── sdd/                   ← Spec-Driven Development artifacts
│   ├── README.md          ← SDD pipeline + Clarity Score gate
│   ├── features/          ← Active specs
│   └── archive/           ← Completed specs
├── cache/                 ← MCP version-aware caches (gitignored)
└── storage/               ← Session state (gitignored)
```

---

## Self-Improvement Protocol — Detail

The trigger rules live in `CLAUDE.md`. This section is the **how**: where each artifact goes, what template to use, what fields to set.

### When to add a KB concept or pattern

**Trigger:** same domain knowledge re-derived in ≥2 sessions.

**Steps:**

1. Pick a domain. If none fits, create one: `cp -r .claude/kb/_templates/* .claude/kb/<domain>/` and register in `_index.yaml`.
2. Pick artifact type:
   - **concept** — atomic idea (≤150 lines). Definitions, invariants, contracts.
   - **pattern** — code-focused recipe (≤200 lines). Reusable code shape.
   - **quick-reference** — lookup table only (≤100 lines).
3. Copy the matching template from `.claude/kb/_templates/`.
4. Update `_index.yaml` (add to `concepts` or `patterns` array).
5. Add a one-line entry in the domain's `index.md`.

### When to add an agent

**Trigger:** same specialist framing + KB reads + role recurs in ≥2 sessions.

**Steps:**

1. Copy `.claude/agents/_specialist-template.md` to `.claude/agents/<name>.md`.
2. Set frontmatter: `name`, `description` (with "Use PROACTIVELY when …"), `tools`, `kb_domains`, `model`.
3. Fill the 5 required sections: Identity, Mandatory Reads, Capabilities, Quality Gate, Response Format.
4. Add a row to the Agents table in `CLAUDE.md`.

### When to add a slash command

**Trigger:** same multi-step workflow run ≥2 times.

**Steps:**

1. Create `.claude/commands/<command-name>.md`.
2. Use this skeleton:

   ```markdown
   ---
   description: One-line summary surfaced in the slash command picker.
   ---

   # /<command-name>

   ## When to use

   …

   ## Steps

   1. …

   ## Output

   …
   ```

3. Reference it in `CLAUDE.md` § Commands if cross-cutting.

### When to add a skill

**Trigger:** Claude needs to use a specific tool/CLI repeatedly and the usage isn't trivial.

**Steps:**

1. Create `.claude/skills/<tool>.md` with frontmatter: `skill`, `description`, `trigger`, `priority`.
2. Document: invocation, common flags, gotchas, examples.

### When to extend `settings.json` permissions

**Trigger:** ≥3 permission prompts on the same command pattern in one session.

**Steps:**

1. Decide team-shared (`settings.json`) vs personal (`settings.local.json`). Read-only MCP and safe bash patterns → team. Anything destructive or env-specific → personal.
2. Use specific patterns (`Bash(uv run pytest *)`) over wildcards (`Bash(*)`).

### When to add a hook

**Trigger:** A class of bug slips through twice and is mechanically detectable.

**Steps:**

1. Write the script in `.claude/hooks/`.
2. Wire in `settings.json` under `hooks.PreToolUse` or `PostToolUse`.
3. Contract: exit 0 = allow, exit 2 = block (write message to stderr).
4. Use `$CLAUDE_PROJECT_DIR` for paths.

---

## Bootstrap Order (when filling this harness)

When the protocol fires for the **first** time on each layer, follow this order so each layer can lean on the one below:

1. **KB** — record knowledge first. Cheap, no behavior change.
2. **Skills** — document tools next. Helps agents.
3. **Commands** — encode workflows. Often the right abstraction over "do this 5-step thing".
4. **Agents** — only when a workflow needs an isolated context window with strict reads.
5. **Hooks** — last. Add only when a bug class has actually bitten and is mechanically catchable.
6. **SDD** — engage when a task is complex enough to warrant brainstorm → define → design (Phase 2+).

---

## Anti-Patterns

- **Premature scaffolding.** Don't create an agent/KB/command "in case we need it". Wait for the second occurrence.
- **Wildcard permissions.** `Bash(*)` defeats the safety model.
- **Duplicated content.** If something lives in code or `_index.yaml`, link to it — don't copy.
- **Editing CLAUDE.md mid-session.** Batch changes; one edit invalidates the prompt cache for the rest of the turn.
- **Hooks that block without a clear remediation.** Every block message must say _what to run_ to unblock.

---

## Where to put what — quick map

| If you have…                      | Put it in…                                                      |
| --------------------------------- | --------------------------------------------------------------- |
| A reusable code shape             | `.claude/kb/<domain>/patterns/<name>.md`                        |
| An atomic concept or contract     | `.claude/kb/<domain>/concepts/<name>.md`                        |
| A multi-step workflow             | `.claude/commands/<name>.md`                                    |
| Repeated specialist framing       | `.claude/agents/<name>.md`                                      |
| A tool/CLI reference              | `.claude/skills/<tool>.md`                                      |
| A pre-commit / pre-bash check     | `.claude/hooks/<name>.sh` + wire in `settings.json`             |
| A pre-implementation spec         | `.claude/sdd/features/<feature>/`                               |
| A pointer to an external resource | Memory (`~/.claude/projects/.../memory/`) as a `reference` type |

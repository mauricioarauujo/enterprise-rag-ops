---
description: Scaffold a new slash command.
---

# /new-command {name}

Create a slash command. See `.claude/STRUCTURE_GUIDE.md` § "When to add a slash command".

## When to use

Same multi-step workflow run ≥2 times.

## Arguments

`$ARGUMENTS` — first positional is the command name (kebab-case).

## Steps

1. Confirm the trigger — the workflow has run ≥2 times.
2. Create `.claude/commands/<name>.md` with this skeleton:

   ```markdown
   ---
   description: One-line summary for the slash-command picker.
   ---

   # /<name>

   ## When to use

   ## Steps

   ## Output
   ```

3. Write concrete, ordered steps. Reference STRUCTURE_GUIDE or KB instead of
   duplicating content.
4. Add a row to the **Command Registry** in `.claude/STRUCTURE_GUIDE.md` § Registries
   (cache-safe — do **not** edit `CLAUDE.md`).

## Output

Report: command name, file path.

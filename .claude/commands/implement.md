---
description: Execute implementation following the SDD design document.
---

# /implement {sprint-N/phase-slug}

Execute implementation. Uses `DESIGN.md` as primary context when it exists; otherwise
works from the phase track directly (backward-compatible — SDD is opt-in).

## Arguments

`$ARGUMENTS` — the feature slug `sprint-N/phase-slug`.

## Steps

1. **Read context**
   - `.claude/sdd/features/{slug}/DESIGN.md` (if it exists) — the file manifest.
   - `.claude/sdd/features/{slug}/DEFINE.md` for acceptance criteria.
   - If no SDD artifacts: read the sprint/phase track directly.

2. **Pre-flight gap check**
   - Scan the manifest for technology areas without KB coverage in `_index.yaml`.
   - Report gaps (missing domain / concept / specialist) and recommend `/new-kb` etc.
   - Report and proceed — do not block.

3. **Execute**
   - Follow the manifest's phase ordering (see `/design`).
   - Delegate file groups to specialist agents per the manifest — when spawning an
     agent, ALWAYS pass `model` explicitly (read the agent's frontmatter).
   - Every new module gets a matching `tests/test_<module>.py`.
   - Eval-path code is not tested against a mocked LLM API — use the cassette/replay
     pattern (see the Phase 2 ADR when it lands).

4. **Quality pass**

   ```bash
   make verify   # format + lint + test
   ```

5. **Report status** — files changed, tests passed/failed, gaps flagged.
   Suggest next step → `/review {slug}`.

#!/usr/bin/env python3
"""Deterministic research-loop / KB health check (the cheap, stdlib-only companion to the
LLM-driven audit-harness). Scaffolded by harness-init to .claude/scripts/. Run from repo root:

    python3 .claude/scripts/kb_health.py

Three read-only checks:
  1. Dossier status drift — docs/research/CONTEXT.md table status vs files on disk
     (🔵/🟢 require findings.md + critique.md unless the row says "(raw)").
  2. KB verification debt — [UNVERIFIED] tags + `confidence: ... CONFLICT` in .claude/kb/,
     and open refinement requests in docs/research/**/critique.md (unclosed loop-backs).
  3. Domain staleness — .claude/kb/_index.yaml `last_updated` older than TTL_DAYS.

Exit 0 = healthy, exit 1 = at least one warning. Stdlib only (no PyYAML — kbind's zero-infra
posture); parses the simple frontmatter/table shapes with regex. Tolerant of missing files
(a fresh repo with no research/KB passes). Wire into a review command or CI as you like.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import sys

ROOT = pathlib.Path(".")
RESEARCH_CTX = ROOT / "docs" / "research" / "CONTEXT.md"
RESEARCH_DIR = ROOT / "docs" / "research"
KB_DIR = ROOT / ".claude" / "kb"
INDEX = KB_DIR / "_index.yaml"
TTL_DAYS = 60

warnings: list[str] = []


def warn(section: str, msg: str) -> None:
    warnings.append(f"[{section}] {msg}")


def check_dossier_drift() -> None:
    if not RESEARCH_CTX.exists():
        return
    for line in RESEARCH_CTX.read_text(encoding="utf-8").splitlines():
        # Only table rows carrying a status emoji are dossier rows.
        status = next((s for s in ("🟡", "🔵", "🟢") if s in line), None)
        if status is None:
            continue
        # The dossier slug is the first backtick-quoted kebab token in the row
        # (column order is not fixed; trailing slash optional).
        m = re.search(r"`([A-Za-z0-9][\w.-]*?)/?`", line)
        if not m:
            continue
        dossier = RESEARCH_DIR / m.group(1)
        is_raw = "(raw)" in line
        has_f = (dossier / "findings.md").exists()
        has_c = (dossier / "critique.md").exists()
        if not dossier.exists():
            warn("drift", f"{dossier} — row exists but folder missing")
        elif status in ("🔵", "🟢") and not is_raw and not (has_f and has_c):
            missing = ", ".join(x for x, ok in (("findings.md", has_f), ("critique.md", has_c)) if not ok)
            warn("drift", f"{dossier} — status {status} but missing {missing} (mark '(raw)' or run refine-research)")
        elif status == "🟡" and has_f:
            warn("drift", f"{dossier} — has findings.md but row still 🟡 (flip to 🔵)")


def check_kb_debt() -> None:
    # KB-file debt only applies once a KB exists…
    if KB_DIR.exists():
        for f in sorted(KB_DIR.rglob("*.md")):
            if "_templates" in f.parts:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if "[UNVERIFIED]" in line:
                    warn("debt", f"{f}:{i} — open [UNVERIFIED] in a KB file")
                if re.search(r">\s*confidence:.*\bCONFLICT\b", line):
                    warn("debt", f"{f}:{i} — confidence CONFLICT not resolved")
    # …but research-loop debt is independent of the KB (D11: research precedes KB, so the
    # open-refinement check must run even on a repo that has no .claude/kb/ yet).
    if RESEARCH_DIR.exists():
        for c in sorted(RESEARCH_DIR.rglob("critique.md")):
            for m in _open_refinement_requests(c):
                warn(
                    "debt",
                    f"{c}:{m} — open refinement request (loop-back not closed); "
                    "mark the heading '— ✅ RESOLVED' or flip the dossier to 🔵/🟢 clean",
                )


# A refinement request is matched as a HEADING (not a prose mention, which was the old
# false-positive source — any line containing the phrase fired forever, even after the
# loop closed). It is OPEN unless either signal of closure is present:
#   (a) the heading carries a resolution token (✅ / RESOLVED / CLOSED / ⚪ consolidated), or
#   (b) the dossier's docs/research/CONTEXT.md row is clean (🔵/🟢, not "pending"/"gaps"/"pass N").
# Closing the loop the documented way (refine-research step 7 flips the row, or step 6 marks
# the heading resolved) now clears the warning — no need to rename the heading to silence it.
_REFINEMENT_HEADING = re.compile(r"^#{1,6}\s*Refinement request\b(?P<tail>.*)$", re.M)
_RESOLUTION_TOKENS = ("✅", "RESOLVED", "CLOSED", "⚪", "consolidated")


def _dossier_is_clean(slug: str) -> bool:
    if not RESEARCH_CTX.exists():
        return False
    for line in RESEARCH_CTX.read_text(encoding="utf-8").splitlines():
        if not re.search(rf"`{re.escape(slug)}/?`", line):
            continue
        clean_status = ("🟢" in line) or ("🔵" in line)
        still_open = re.search(r"pending|gaps|pass\s*\d+", line, re.IGNORECASE)
        return bool(clean_status and not still_open)
    return False


def _open_refinement_requests(critique: pathlib.Path) -> list[int]:
    text = critique.read_text(encoding="utf-8")
    clean = _dossier_is_clean(critique.parent.name)
    if clean:
        return []
    open_lines: list[int] = []
    for m in _REFINEMENT_HEADING.finditer(text):
        if any(tok in m.group("tail") for tok in _RESOLUTION_TOKENS):
            continue
        open_lines.append(text[: m.start()].count("\n") + 1)
    return open_lines


def check_staleness() -> None:
    if not INDEX.exists():
        return
    today = datetime.date.today()
    text = INDEX.read_text(encoding="utf-8")
    # Pair each domain slug (best-effort) with the nearest last_updated date below it.
    slug = None
    for line in text.splitlines():
        s = re.search(r"(?:- )?slug:\s*['\"]?([\w-]+)", line)
        if s:
            slug = s.group(1)
        d = re.search(r"last_updated:\s*['\"]?(\d{4}-\d{2}-\d{2})", line)
        if d:
            try:
                age = (today - datetime.date.fromisoformat(d.group(1))).days
            except ValueError:
                continue
            if age > TTL_DAYS:
                warn("stale", f"{slug or '<domain>'} — last_updated {d.group(1)} is {age}d old (> {TTL_DAYS}d); run update-kb")


# SSoT for KB line budgets (the four numbers; prose/template copies should reference THIS).
# Enforced here as a script instead of LLM-eyeballing (modulo04 `validador.py` thesis / D40).
BUDGETS = {"concept": 150, "pattern": 200, "quick-reference": 100, "index": 50}


def _budget_kind(f: pathlib.Path) -> str | None:
    if "concepts" in f.parts:
        return "concept"
    if "patterns" in f.parts:
        return "pattern"
    if f.name == "quick-reference.md":
        return "quick-reference"
    if f.name == "index.md":
        return "index"
    return None


def check_budgets() -> None:
    """A KB file over its template-kind line budget — over-budget = the file is doing too much."""
    if not KB_DIR.exists():
        return
    for f in sorted(KB_DIR.rglob("*.md")):
        if "_templates" in f.parts:
            continue
        kind = _budget_kind(f)
        if kind is None:
            continue
        n = len(f.read_text(encoding="utf-8").splitlines())
        if n > BUDGETS[kind]:
            warn("budget", f"{f} — {n} lines > {kind} budget {BUDGETS[kind]} (split it)")


def main() -> int:
    check_dossier_drift()
    check_kb_debt()
    check_staleness()
    check_budgets()
    if warnings:
        print(f"✗ kb-health: {len(warnings)} warning(s):", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        return 1
    print("✓ kb-health: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

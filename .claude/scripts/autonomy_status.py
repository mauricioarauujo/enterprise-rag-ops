#!/usr/bin/env python3
"""autonomy_status.py — render the 'you-are-here' autonomy-ladder position (Sprint A2, D51).

The deterministic render behind kbind-guide's "where am I on the ladder?". The state-logic — the
next-rung family (over `unlocked_through`) and the calibration-status family (over `target_level`
vs `unlocked_through`) — is CODE, so it is exhaustive + disjoint by construction (no contradictory
render, A2 F7), and the no-reproduced-ladder (AC-11) / no-computed-path (AC-14) rules are
unit-testable against this output. kbind-guide prints this verbatim and adds the
operating/unlocked/desired framing (AC-7b).

  python autonomy_status.py <kbind.yaml>     -> prints the render, exit 0 (never raises on a bad block)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

POINTER = "Unlock criteria: see ADR-0013 § ladder table."
FIELDS = ("current_level", "unlocked_through", "target_level")
_AUTONOMY_RE = re.compile(r"^autonomy:\s*(#.*)?$")
_FIELD_RE = re.compile(r"^\s+(\w+):\s*[Ll]([1-6])\b")


def read_block(text: str) -> dict | None:
    """Return {current_level, unlocked_through, target_level} as ints 1..6, or None if absent/partial."""
    vals: dict[str, int] = {}
    in_block = False
    for raw in text.splitlines():
        body = raw.rstrip()
        if _AUTONOMY_RE.match(body):
            in_block = True
            continue
        if in_block and body and not body[0].isspace() and not body.lstrip().startswith("#"):
            break
        if in_block:
            m = _FIELD_RE.match(body)
            if m and m.group(1) in FIELDS:
                vals[m.group(1)] = int(m.group(2))
    return vals if all(f in vals for f in FIELDS) else None


def render(current: int, unlocked: int, target: int) -> str:
    """The canonical render. Two orthogonal families, each exhaustive + disjoint (AC-7a/8a/9a..c)."""
    lines = [f"you-are-here: current=L{current} unlocked=L{unlocked} target=L{target}"]
    # next-rung family (over unlocked_through)
    if unlocked < 5:
        lines.append(f"Next rung to earn: L{unlocked + 1}.")
    else:
        lines.append("No higher rung is on the near roadmap; L6 is out of near-scope (ADR-0013).")
    # calibration-status family (over target vs unlocked)
    if target <= unlocked:
        lines.append("No calibration pending: your desired rung is within what is unlocked.")
    elif unlocked < 5:
        lines.append("Gate: the evaluator must be calibrated to earn the next rung (ADR-0014 / D50).")
    else:
        lines.append(f"Your desired rung (L{target}) is beyond the near roadmap; no calibration path.")
    lines.append(POINTER)
    return "\n".join(lines)


def render_unset() -> str:
    """AC-10: absent-or-partial block — state unset, point to the capture, never raise."""
    return (
        "autonomy: not set in this repo's .claude/kbind.yaml.\n"
        "Run `harness-init` (or the autonomy-intent capture step) to record your target rung.\n"
        + POINTER
    )


def build_render(text: str) -> str:
    blk = read_block(text)
    if blk is None:
        return render_unset()
    return render(blk["current_level"], blk["unlocked_through"], blk["target_level"])


# --- AC-11 / AC-14 render-section rules (the seam predicates; unit-tested against build_render) ---

def reproduces_ladder(text: str) -> bool:
    """AC-11: True if `text` reproduces the ADR-0013 ladder as a table or a rung-list."""
    lines = text.splitlines()
    table_rows = 0
    for ln in lines:
        if ln.count("|") < 2:
            continue
        cells = [c.strip() for c in ln.split("|") if c.strip()]  # columns, style-independent
        if len(cells) >= 3 and re.match(r"^\**L[1-6]\**$", cells[0]):  # >=3 columns, first cell a rung
            table_rows += 1
    if table_rows >= 2:
        return True
    list_rows = sum(
        1 for ln in lines
        if re.match(r"^\s*[-*]?\s*\**L[1-6]\b", ln) and len(ln.split()) >= 4
    )
    return list_rows >= 3


_COMPUTED = [
    re.compile(p, re.I)
    for p in (r"%", r"ETA", r"estimat", r"\bdays?\b", r"\bweeks?\b",
              r"\d+\s+steps?", r"\d+\s*/\s*\d+", r"\d+\s+of\s+\d+", r"\d+\s*rungs?")
]


def has_computed_path(text: str) -> bool:
    """AC-14: True if `text` contains a computed path / ETA token (the deferred intent-03B surface)."""
    return any(p.search(text) for p in _COMPUTED)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: autonomy_status.py <kbind.yaml>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    print(build_render(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

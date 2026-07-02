#!/usr/bin/env python3
"""autonomy_set_target.py — write ONLY autonomy.target_level in .claude/kbind.yaml (Sprint A2, D51).

The deterministic writer behind the harness-init / harness-adopt / kbind-guide autonomy-intent
capture. `target_level` is INTENT metadata that tunes nothing — it cannot raise `unlocked_through`
(the D43 seal). This helper is the structural form of that inert-by-construction guarantee (AC-2):
it does an in-place single-line rewrite of the `target_level` line and never touches any other
field (`current_level` / `unlocked_through` / `risk_tier_gates`), so the fence holds by
construction, not by prompt-discipline.

  python autonomy_set_target.py <kbind.yaml> <L1..L6 | --default>     exit 0 / 2

`--default` writes L3 (the decline path, AC-1b). An out-of-ladder level is rejected (exit 2, AC-5a)
and writes nothing; the calling skill re-prompts (AC-5b). A manifest with no `autonomy.target_level`
line is a finding (exit 2) — this helper sets an existing field, it does not scaffold the block.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

VALID = {f"L{i}" for i in range(1, 7)}  # L1..L6 — L6 is a valid intent though out of near-scope (ADR-0013)
DEFAULT = "L3"

_TARGET_RE = re.compile(r"^(?P<indent>\s+)target_level:(?P<gap>\s*)(?P<val>\S+)(?P<rest>.*)$")
_AUTONOMY_RE = re.compile(r"^autonomy:\s*(#.*)?$")


def validate_level(raw: str) -> str | None:
    """Normalise 'l4'/'L4' -> 'L4'; return None if not a valid ladder rung."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    return s if s in VALID else None


def rewrite_target(text: str, level: str) -> str:
    """Return `text` with autonomy.target_level set to `level`, every other byte preserved.

    Raises ValueError if there is no target_level line under an `autonomy:` block.
    """
    lines = text.splitlines(keepends=True)
    in_block = False
    for i, line in enumerate(lines):
        body = line.rstrip("\n")
        if _AUTONOMY_RE.match(body):
            in_block = True
            continue
        if in_block and body and not body[0].isspace() and not body.lstrip().startswith("#"):
            in_block = False  # dedented to a new top-level key without hitting target_level
        if in_block:
            m = _TARGET_RE.match(body)
            if m:
                newbody = f"{m['indent']}target_level:{m['gap']}{level}{m['rest']}"
                lines[i] = newbody + ("\n" if line.endswith("\n") else "")
                return "".join(lines)
    raise ValueError("no autonomy.target_level line found (this helper sets an existing field)")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: autonomy_set_target.py <kbind.yaml> <L1..L6 | --default>", file=sys.stderr)
        return 2
    level = DEFAULT if argv[2] == "--default" else validate_level(argv[2])
    if level is None:
        print(f"✗ rejected: {argv[2]!r} is not a ladder rung (L1..L6) — nothing written", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    try:
        new = rewrite_target(path.read_text(encoding="utf-8"), level)
    except ValueError as exc:
        print(f"✗ {path}: {exc}", file=sys.stderr)
        return 2
    path.write_text(new, encoding="utf-8")
    print(f"✓ autonomy.target_level = {level} (intent only; unlocks nothing — the evaluator raises unlocked_through)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

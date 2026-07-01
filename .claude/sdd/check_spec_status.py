#!/usr/bin/env python3
"""Minimal CI status-check for the Spec layer (docs/specs/CONTEXT.md, Rule 12).

Don't claim a lifecycle you don't watch. This enforces the status ladder mechanically so the
`status:` field can't silently rot. Stdlib-only (no PyYAML): parses the simple key/value + flat
list frontmatter the template emits.

Fails (exit 1) when, for any spec under the given root:
  - `status` is missing or outside {draft, approved, implemented, archived};
  - `governing_adrs` is missing/empty (every contract must trace to >=1 decision);
  - `status: implemented` but a declared `ssot:` pointer path does not exist on disk;
  - a `CHARTER.md` (L0 Intent) exists but the spec's `source_charters` is empty AND it does not
    declare `infra: true` (an ADR-born infra module legitimately traces to no charter — but it must
    say so explicitly; a silent empty is the untraced-spec drift, now enforced not advised).

`stale` is NOT a ladder state — it is a flag audit-harness raises on drift, not a value here.

Usage:
    python docs/specs/check_spec_status.py docs/specs
"""

from __future__ import annotations

import sys
from pathlib import Path

ALLOWED_STATUS = {"draft", "approved", "implemented", "archived"}


def parse_frontmatter(text: str) -> dict | None:
    """Return the YAML-ish frontmatter as a dict, or None if absent.

    Supports `key: scalar`, `key: []`, and inline flat lists `key: [a, b]`. Comments (`#`) and
    blank lines are ignored. Good enough for the template's frontmatter; not a YAML parser.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    out: dict[str, object] = {}
    for raw in block.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            out[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
        else:
            out[key] = val.strip("\"'")
    return out


def _is_true(val: object) -> bool:
    return str(val).strip().lower() == "true"


def check_spec(path: Path, root: Path, charter_exists: bool = False) -> list[str]:
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    rel = path.relative_to(root)
    if fm is None:
        return [f"{rel}: no YAML frontmatter (expected `status:` block)"]

    errors: list[str] = []
    status = fm.get("status")
    if status not in ALLOWED_STATUS:
        errors.append(f"{rel}: status={status!r} not in {sorted(ALLOWED_STATUS)}")

    if not fm.get("governing_adrs"):
        errors.append(f"{rel}: governing_adrs is empty (every contract traces to a decision)")

    # Charter trace (enforced once a CHARTER.md exists): a spec must trace to the L0 Intent, or
    # declare itself infra (ADR-born, no charter trace) — a silent empty is the untraced-spec drift.
    if charter_exists and not fm.get("source_charters") and not _is_true(fm.get("infra")):
        errors.append(
            f"{rel}: source_charters empty (trace to CHARTER.md, or set `infra: true` if this "
            f"module is ADR-born and owns no L0 intent)"
        )

    if status == "implemented":
        ssot = fm.get("ssot") or []
        if not ssot:
            errors.append(f"{rel}: status=implemented but no ssot: pointers (Rule 12 handover)")
        for pointer in ssot:
            target = pointer.split("#", 1)[0].split(":", 1)[0].strip()
            if target and not (root.parent / target).exists() and not Path(target).exists():
                errors.append(f"{rel}: ssot pointer does not exist on disk: {target!r}")
    return errors


def charter_trace(specs_fm: dict, charter_exists: bool, root: Path) -> list[str]:
    """Orphan-charter warning (AC-4, Sprint A1 / P-2). The per-Spec `source_charters`-empty case is
    now a hard error in `check_spec` (enforced, not advised). This keeps only the softer signal: a
    CHARTER.md that NO Spec traces to. Returns warnings; never fails the build (fail-soft)."""
    if not charter_exists:
        return []
    referenced: set[str] = set()
    for fm in specs_fm.values():
        referenced |= set((fm or {}).get("source_charters") or [])
    if not referenced:
        return ["⚠ CHARTER.md is referenced by no Spec (orphan charter — wire source_charters in ≥1 Spec)"]
    return []


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_spec_status.py <specs-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    # Spec files: every .md except the index/template/archive scaffolding.
    skip_names = {"CONTEXT.md", "README.md", "_template.md", "CHARTER.md"}
    specs = [
        p
        for p in root.rglob("*.md")
        if p.name not in skip_names
        and not p.name.startswith("_")
        and "_archive" not in p.parts
    ]
    # Folder-specs: the narrative README.md IS the spec (it carries the frontmatter).
    specs += [
        p for p in root.rglob("README.md") if p.parent != root and "_archive" not in p.parts
    ]

    # A CHARTER.md (L0 Intent) turns on enforced source_charters tracing (per check_spec).
    charter_exists = (root / "CHARTER.md").exists() or any(root.rglob("CHARTER.md"))

    errors: list[str] = []
    specs_fm: dict = {}
    for spec in sorted(set(specs)):
        specs_fm[spec] = parse_frontmatter(spec.read_text(encoding="utf-8")) or {}
        errors.extend(check_spec(spec, root, charter_exists))

    # Charter trace (AC-4): the orphan-charter case stays a soft warning, never blocks.
    for w in charter_trace(specs_fm, charter_exists, root):
        print(f"  {w}", file=sys.stderr)

    if errors:
        print(f"✗ spec-status check failed ({len(errors)} issue(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"✓ spec-status check passed ({len(set(specs))} spec(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

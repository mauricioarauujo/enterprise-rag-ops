#!/usr/bin/env python3
"""kbind_yaml_check.py — mechanical validation of `.claude/kbind.yaml` (the contract manifest).

`audit-harness` SPECIFIES two invariants over this file in prose; a typo or a hand-edit would
pass with no backstop (the same silent-drift class `registry_parity.py` closes for the KB). This
makes them deterministic:

  1. **Manifest-key lint (silent-ignore guard).** The runtime ignores keys it doesn't recognize, so
     a typo (`harness_code:` for `harness_and_code:`) silently disables a rule. Every key under
     `layout:`, `language.artifact:`, `ci:`, and `autonomy:` must be in the contract's known set
     (SSoT: `conventions/contract-v1.md`).
  2. **Autonomy unlock guard (ADR-0013).** `autonomy.current_level` must not exceed
     `autonomy.unlocked_through` — autonomy claimed past what the Phase-2 evaluator (ADR-0014) has
     unlocked. `unlocked_through` is raised only by evaluator calibration, never by hand.
  3. **Contract-version guard (ADR-0005).** `conventions:` must be present and well-formed, and its
     MAJOR must match the contract this plugin speaks. ADR-0005's load-bearing promise is that a
     `/plugin update` never silently breaks a conforming repo, and major-version compatibility is
     the invariant that promise rests on — but nothing read the key, so `conventions: v99` and
     `conventions: banana` both linted clean, as did a manifest with no `conventions:` at all. A
     declared version nobody checks is a comment.

Stdlib-only — parses the small indentation-based YAML subset the template emits (nested maps of
scalars; no lists, anchors, or multi-line strings). An unparseable manifest fails (exit 2): a
contract file we can't read is itself a finding, not a silent pass.

Usage:  python kbind_yaml_check.py <path/to/.claude/kbind.yaml>     exit 0/1/2
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# The conventions contract this plugin generation speaks (SSoT: conventions/contract-v1.md).
# Compatibility is MAJOR-ONLY by ADR-0005 — a repo on the same major is conforming even if the
# plugin has since added optional keys. Bump this ONLY alongside a contract-vN+1 document.
CONVENTIONS_MAJOR = 1

_CONVENTIONS_RE = re.compile(r"^v(\d+)$")

# SSoT for the lint = conventions/contract-v1.md. Keep these sets in sync with that doc.
KNOWN_KEYS = {
    "layout": {"router", "docs_index", "roadmap", "adrs", "specs_index", "research_index", "kb_registry"},
    "language.artifact": {"domain_content", "harness_and_code", "terms_of_art"},
    "ci": {"provider", "workflow", "test_command", "run_command", "deploy_command"},
    "autonomy": {"target_level", "current_level", "unlocked_through", "risk_tier_gates"},
}

# A layout AREA's value is a bare path — or the declared-private nested map (contract-v1
# § Declared-private areas): `path` required, `private` optional true/false.
LAYOUT_AREA_KEYS = {"path", "private"}


def _preprocess(text: str) -> list[str]:
    """Drop comments + blank lines, preserve leading indentation."""
    out: list[str] = []
    for raw in text.splitlines():
        code = raw.split("#", 1)[0].rstrip()
        if code.strip():
            out.append(code)
    return out


def _parse_block(lines: list[str], idx: int, indent: int) -> tuple[dict, int]:
    """Parse an indentation-delimited mapping into a nested dict. Returns (dict, next_idx)."""
    out: dict[str, object] = {}
    n = len(lines)
    while idx < n:
        cur = len(lines[idx]) - len(lines[idx].lstrip())
        if cur < indent:
            break
        stripped = lines[idx].strip()
        if ":" not in stripped:
            idx += 1
            continue
        key, _, val = stripped.partition(":")
        key, val = key.strip(), val.strip()
        if val:
            out[key] = val
            idx += 1
        elif idx + 1 < n and (len(lines[idx + 1]) - len(lines[idx + 1].lstrip())) > cur:
            child_indent = len(lines[idx + 1]) - len(lines[idx + 1].lstrip())
            child, idx = _parse_block(lines, idx + 1, child_indent)
            out[key] = child
        else:
            out[key] = {}
            idx += 1
    return out, idx


def parse_manifest(text: str) -> dict:
    tree, _ = _parse_block(_preprocess(text), 0, 0)
    return tree


def _level_num(val: object) -> int | None:
    """`L3` -> 3. None if not an L<int> token."""
    if not isinstance(val, str):
        return None
    s = val.strip()
    if len(s) >= 2 and s[0] in "Ll" and s[1:].isdigit():
        return int(s[1:])
    return None


def _check_conventions(tree: dict) -> list[str]:
    """Guard 3 — the manifest declares a contract version, and it is one we speak.

    Fail-closed on ABSENCE as well as mismatch: an unversioned manifest is unauditable, not
    "safely current" (the same reasoning that makes the autonomy block scaffold ACTIVE, D48).
    """
    raw = tree.get("conventions")
    if raw is None:
        return ["conventions: key missing — the manifest declares no contract version "
                f"(expected 'conventions: v{CONVENTIONS_MAJOR}'; ADR-0005)"]
    if isinstance(raw, dict) or not str(raw).strip():
        return [f"conventions: must be a version scalar like 'v{CONVENTIONS_MAJOR}', got {raw!r}"]
    val = str(raw).strip()
    m = _CONVENTIONS_RE.match(val)
    if not m:
        return [f"conventions: malformed version {val!r} — expected 'v<major>' "
                f"(e.g. 'v{CONVENTIONS_MAJOR}'; ADR-0005)"]
    major = int(m.group(1))
    if major != CONVENTIONS_MAJOR:
        return [f"conventions: repo targets contract v{major}, this plugin speaks "
                f"v{CONVENTIONS_MAJOR} — run /kbind:harness-adopt --migrate (ADR-0005 "
                f"compatibility is major-version only; do not hand-edit this key to dodge it)"]
    return []


def lint(tree: dict) -> list[str]:
    """Return the list of contract violations (empty = clean)."""
    errors: list[str] = _check_conventions(tree)

    def check_keys(node: object, known: set[str], where: str) -> None:
        if not isinstance(node, dict):
            return
        for k in node:
            if k not in known:
                errors.append(f"{where}: unknown key {k!r} (known: {', '.join(sorted(known))})")

    layout = tree.get("layout")
    check_keys(layout, KNOWN_KEYS["layout"], "layout")
    if isinstance(layout, dict):
        # Nested (declared-private) area shape: {path: <p>, private: true|false}.
        for area, val in layout.items():
            if not isinstance(val, dict):
                continue
            check_keys(val, LAYOUT_AREA_KEYS, f"layout.{area}")
            if "path" not in val or not str(val.get("path", "")).strip():
                errors.append(f"layout.{area}: nested entry needs a non-empty 'path'")
            private = val.get("private")
            if private is not None and str(private).strip().lower() not in ("true", "false"):
                errors.append(f"layout.{area}: 'private' must be true or false, got {private!r}")

    language = tree.get("language")
    if isinstance(language, dict):
        check_keys(language.get("artifact"), KNOWN_KEYS["language.artifact"], "language.artifact")

    check_keys(tree.get("ci"), KNOWN_KEYS["ci"], "ci")

    autonomy = tree.get("autonomy")
    if isinstance(autonomy, dict):
        # risk_tier_gates is a known key whose VALUE is a nested map — lint the top level only.
        check_keys({k: v for k, v in autonomy.items()}, KNOWN_KEYS["autonomy"], "autonomy")
        cur, unlocked = _level_num(autonomy.get("current_level")), _level_num(autonomy.get("unlocked_through"))
        if cur is not None and unlocked is not None and cur > unlocked:
            errors.append(
                f"autonomy: current_level (L{cur}) exceeds unlocked_through (L{unlocked}) — "
                f"autonomy claimed past what the evaluator has unlocked (ADR-0013)"
            )
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: kbind_yaml_check.py <path/to/.claude/kbind.yaml>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    try:
        tree = parse_manifest(path.read_text(encoding="utf-8"))
    except Exception as exc:  # a contract file we can't parse is a finding, not a pass
        print(f"✗ kbind.yaml: could not parse manifest: {exc}", file=sys.stderr)
        return 2
    errors = lint(tree)
    if errors:
        print(f"✗ kbind.yaml: {len(errors)} contract violation(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"✓ kbind.yaml: contract v{CONVENTIONS_MAJOR} + manifest keys known "
          f"+ autonomy posture consistent ({path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

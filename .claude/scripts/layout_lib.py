#!/usr/bin/env python3
"""layout_lib.py — the ONE answer to "where does area X live in this repo?" (contract-v1 Clause 1).

The contract says it plainly: *"`audit-harness` and every command resolve an area **through
`layout:` first, then the default**"*. Until now nothing in the product made that easy. Area
resolution existed as three private, ad-hoc implementations that never met —
`seed_sync._resolve_specs_dir` (specs only), `doc_budget.layout_budgets` (budget globs only), and
`adr_trace_check`'s CLI default — and there was no entry point a script or a session could ask.

That gap is not academic. It has produced the same defect three times:
  * `doc_budget` was keyed on DEFAULT paths, so 23 ADRs / 1,982 lines went unbudgeted in exactly
    the two repos that used the contract's own override (fixed 0.15.1);
  * the E3 DEFINE pinned a literal `docs/adr-critiques/` and never mentioned `layout:` at all,
    while all three consumers remap `adrs`;
  * a session looked for a CHARTER at the canonical `docs/specs/CHARTER.md`, reported it missing,
    and was wrong — the repo remaps its spec area and the file was there all along.

A checker that punishes the hardcoded path while the right answer stays inconvenient is a checker
that becomes noise and gets muted. So the rule is mechanized in BOTH directions: `layout_check.py`
catches the literal, and this module removes the reason to write one.

Usage (importable):
    import layout_lib as L
    L.resolve("adrs", repo)        -> "docs/architecture/adrs"   (or the default)
    L.resolve_dir("kb_registry", repo) -> ".claude/kb"           (index files -> their directory)
    L.overrides(repo)              -> {"adrs": "docs/architecture/adrs"}   (only what DIFFERS)
    L.is_private("roadmap", repo)  -> True | False

Usage (standalone — so a session can ASK instead of guessing):
    python3 layout_lib.py <repo-root>            # every area, resolved, marked where overridden
    python3 layout_lib.py <repo-root> adrs       # one area, bare path, script-friendly
    python3 layout_lib.py <repo-root> specs_index --dir   # that area's DIRECTORY (for shell callers)

Fail-open by construction, matching the two resolvers it generalizes: an absent, unreadable or
malformed manifest yields the documented defaults, never an exception. A repo with no
`.claude/kbind.yaml` is a repo using every default — that is the contract's "scales to zero"
posture, not an error.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The area vocabulary is CLOSED and its SSoT is contract-v1 Clause 1 / `kbind_yaml_check.KNOWN_KEYS`
# ("audit-harness flags any other key — the runtime silently ignores keys it doesn't recognize, so a
# typo would disable a remap with no error"). Kept in the same order the contract lists them.
#
# The default is the CANONICAL AREA NAME the contract pins, not a guess. `adrs` is the one
# DIRECTORY area; every other area is a single index FILE — the same split `doc_budget` encodes as
# `_LAYOUT_BUDGETS`'s is_dir flag, stated once here instead of re-derived per caller.
# layout-ok: THIS TABLE IS THE DEFAULTS. It is the SSoT every other caller resolves through;
# there is nowhere further to defer to.
AREA_DEFAULTS: dict[str, str] = {
    "router": "CLAUDE.md",
    "docs_index": "docs/CONTEXT.md",
    "roadmap": "docs/roadmap.md",
    "adrs": "docs/adrs",
    "specs_index": "docs/specs/CONTEXT.md",
    "research_index": "docs/research/CONTEXT.md",
    "kb_registry": ".claude/kb/_index.yaml",
}
DIR_AREAS: frozenset[str] = frozenset({"adrs"})

MANIFEST = ".claude/kbind.yaml"


def manifest_status(repo_root: Path | str = ".") -> str:
    """`none` (no manifest — every area is a default), `ok`, or `unreadable`.

    The third state exists because it BIT. `layout_lib` was seeded into repos while its parser
    (`kbind_yaml_check`) was not, so `_manifest_layout` hit ImportError and fell open to the
    defaults — and the resolver then answered `docs/specs` for a repo whose specs are at
    `.claude/sdd`, confidently and silently. A resolver returning the wrong path is worse than no
    resolver. Resolution still fails OPEN (that is its contract), but the condition is now
    reportable, and the CLI says so rather than implying a manifest was read.
    """
    path = Path(repo_root) / MANIFEST
    if not path.is_file():
        return "none"
    try:
        from kbind_yaml_check import parse_manifest  # noqa: F401 — availability probe
        parse_manifest(path.read_text(encoding="utf-8"))
    except Exception:
        return "unreadable"
    return "ok"


def _manifest_layout(repo_root: Path) -> dict:
    """The raw `layout:` map, or {} — fail-open on every failure mode.

    Reuses `kbind_yaml_check.parse_manifest` rather than forking a second YAML reader; two
    parsers for one manifest is the hand-kept-mirror failure this project keeps recording.
    """
    path = repo_root / MANIFEST
    if not path.is_file():
        return {}
    try:
        from kbind_yaml_check import parse_manifest  # sibling script — reuse, don't duplicate
        layout = parse_manifest(path.read_text(encoding="utf-8")).get("layout")
    except Exception:
        return {}
    return layout if isinstance(layout, dict) else {}


def _declared(area: str, repo_root: Path) -> tuple[str | None, bool]:
    """(declared path or None, private flag) for one area.

    An area's value is a bare path OR the declared-private nested map documented in contract-v1
    (`{path: ..., private: true|false}`) — a brownfield repo may deliberately keep an area
    untracked, which is a policy, not drift. Both shapes resolve to the same path here so no
    caller has to know which was written.
    """
    val = _manifest_layout(repo_root).get(area)
    private = False
    if isinstance(val, dict):
        private = bool(val.get("private") is True or str(val.get("private", "")).lower() == "true")
        val = val.get("path")
    if not isinstance(val, str) or not val.strip():
        return None, private
    return val.strip().strip("/"), private


def areas() -> tuple[str, ...]:
    """The closed area vocabulary, in contract order."""
    return tuple(AREA_DEFAULTS)


def resolve(area: str, repo_root: Path | str = ".") -> str:
    """Repo-relative path for `area`: the `layout:` override first, then the documented default.

    Raises KeyError for an area outside the closed set — a typo must fail loudly here, because
    silently returning a default is exactly the failure the contract warns about for the manifest.
    """
    if area not in AREA_DEFAULTS:
        raise KeyError(f"unknown layout area {area!r} — known: {', '.join(AREA_DEFAULTS)}")
    declared, _ = _declared(area, Path(repo_root))
    return declared or AREA_DEFAULTS[area]


def resolve_dir(area: str, repo_root: Path | str = ".") -> str:
    """The DIRECTORY for an area: the area path itself for `adrs`, the parent for index files.

    `kb_registry` -> `.claude/kb` is the case D75's provenance checker needs: the KB pages live
    beside the registry, and hardcoding `.claude/kb/` there would have made the checker the fourth
    instance of the defect it ships alongside.
    """
    p = resolve(area, repo_root)
    return p if area in DIR_AREAS else (str(Path(p).parent) if "/" in p else ".")


def is_private(area: str, repo_root: Path | str = ".") -> bool:
    """True if the repo declared this area private (untracked by policy — contract-v1)."""
    if area not in AREA_DEFAULTS:
        raise KeyError(f"unknown layout area {area!r}")
    return _declared(area, Path(repo_root))[1]


def overrides(repo_root: Path | str = ".") -> dict[str, str]:
    """Only the areas whose resolved path DIFFERS from the default (the interesting set)."""
    root = Path(repo_root)
    return {a: resolve(a, root) for a in AREA_DEFAULTS if resolve(a, root) != AREA_DEFAULTS[a]}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    want_dir = "--dir" in argv
    argv = [a for a in argv if a != "--dir"]
    if not argv or len(argv) > 2:
        print("usage: layout_lib.py <repo-root> [<area>] [--dir]", file=sys.stderr)
        print(f"       areas: {', '.join(AREA_DEFAULTS)}", file=sys.stderr)
        return 2
    root = Path(argv[0])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    if len(argv) == 2:  # one area, bare path on stdout — script-friendly, no decoration
        # A manifest that exists but cannot be read means the answer below is a DEFAULT wearing
        # the appearance of a resolution. Say so on stderr; stdout stays clean for the caller.
        if manifest_status(root) == "unreadable":
            print(f"○ layout: {MANIFEST} exists but could not be parsed — answering with "
                  f"DEFAULTS, which may be wrong for this repo. If this is a repo-resident copy, "
                  f"kbind_yaml_check.py must sit beside layout_lib.py (run /kbind:harness-update).",
                  file=sys.stderr)
        try:
            print(resolve_dir(argv[1], root) if want_dir else resolve(argv[1], root))
        except KeyError as e:
            print(str(e).strip('"'), file=sys.stderr)
            return 2
        return 0

    over = overrides(root)
    has_manifest = (root / MANIFEST).is_file()
    for area in AREA_DEFAULTS:
        path = resolve(area, root)
        mark = " (override)" if area in over else ""
        priv = " [declared-private]" if is_private(area, root) else ""
        exists = "" if (root / path).exists() else "   ← not present"
        print(f"  {area:<15} {path}{mark}{priv}{exists}")
    if not has_manifest:
        print(f"○ no {MANIFEST} — every area shown is the documented default")
    elif manifest_status(root) == "unreadable":
        print(f"○ {MANIFEST} exists but could not be parsed — every area above is a DEFAULT, not "
              f"a resolution (is kbind_yaml_check.py beside this script?)")
    else:
        print(f"{len(over)} override(s) declared" if over else "0 overrides — all areas default")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

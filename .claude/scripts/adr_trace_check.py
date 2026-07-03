#!/usr/bin/env python3
"""Deterministic ADR↔research traceability check (the decision-layer twin of
`check_spec_status.py`'s Spec↔ADR trace).

Don't claim a lifecycle you don't watch. The harness promises "research → ADR" as an enforced,
traceable step — this enforces it mechanically so an Accepted decision can't silently skip its
evidence. Stdlib-only (no PyYAML): parses the `**Status:** / **Research:**` header lines the ADR
template emits (`templates/adrs/_template.md`).

Gates ONLY ADRs whose Status contains "Accepted" (Proposed/Rejected/Superseded pass untouched).
An Accepted ADR passes when its `**Research:**` line either:
  - names >=1 path token that EXISTS on disk (tokens containing "/" or ending in .md, resolved
    against the CWD and against the adr-dir's parent-of-parent — the repo root for docs/adrs);
    trailing `(...)` annotations are stripped; OR
  - carries an EXPLICIT waiver — the line contains `waiver:` (e.g.
    `**Research:** — (waiver: founder-call — ratified in-session 2026-06-11)`). Waived ADRs are
    counted in the success summary ("N waived") so waivers stay visible — explicit beats silent,
    mirroring how check_spec_status treats `infra: true`.

Fails (exit 1) when an Accepted ADR has a bare "—", an empty/{{placeholder}} value, only
unresolvable paths, or no `**Research:**` line at all. Skips `_template.md`, `README.md`, any
`_*`-prefixed file, and `_archive/` trees; only `NNNN-*.md` files are ADRs.

**Vacuous-pass guard (brownfield honesty).** An ADR with no parseable `**Status:**` header at
all (legacy shapes: `## Status` sections, MADR bullets — every brownfield predates the template
by construction) is invisible to this gate: it can neither be gated nor skipped-on-purpose. Those
files are counted as **unparsed-status** in the summary and a stderr warning names them, so a CI
gate that is green because it parsed nothing reads as VACUOUS instead of healthy. Exit stays 0 —
advisory-honest, not newly blocking (converge by authoring from `_template.md` or adding a
`**Status:**` line to legacy ADRs).

Usage:
    python3 adr_trace_check.py [<adr-dir>]        # default: docs/adrs; exit 0/1/2
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_ADR_DIR = "docs/adrs"
FIX_HINT = "add Research: <dossier path> or an explicit waiver (waiver: ...)"

_ADR_NAME_RE = re.compile(r"^\d{4}-.*\.md$")
_HEADER_RE = re.compile(r"^\*\*(?P<key>Status|Research):\*\*\s*(?P<val>.*)$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_PAREN_RE = re.compile(r"\([^)]*\)")
_BARE_DASH = {"", "—", "-", "–"}


def iter_adr_files(adr_dir: Path) -> list[Path]:
    """The ADR files to gate: `NNNN-*.md`, excluding `_archive/` trees (the NNNN- pattern
    already excludes `_template.md`, `README.md`, and `_*`-prefixed files)."""
    return sorted(
        p
        for p in adr_dir.rglob("*.md")
        if _ADR_NAME_RE.match(p.name)
        and not p.name.startswith("_")
        and "_archive" not in p.parts
    )


def parse_header(text: str) -> dict[str, str]:
    """Return {'Status': ..., 'Research': ...} from the template's `**Key:**` header lines
    (first occurrence wins; inline HTML comments stripped). Missing keys are absent."""
    out: dict[str, str] = {}
    for line in _COMMENT_RE.sub("", text).splitlines():
        m = _HEADER_RE.match(line.strip())
        if m and m.group("key") not in out:
            out[m.group("key")] = m.group("val").strip()
    return out


def path_tokens(value: str) -> list[str]:
    """Whitespace/comma-separated tokens of the Research value that look like paths (contain
    "/" or end in .md), with trailing `(...)` annotations and wrapping punctuation stripped."""
    bare = _PAREN_RE.sub(" ", value)
    tokens = []
    for raw in re.split(r"[\s,]+", bare):
        # Strip wrapping punctuation, but only TRAILING dots: a leading dot is a dot-directory
        # path (`.claude/kb/_research/…` — a real brownfield research zone), not punctuation.
        tok = raw.strip("`\"',;:()[]<>").rstrip(".")
        if tok and ("/" in tok or tok.endswith(".md")):
            tokens.append(tok)
    return tokens


def _resolves(token: str, adr_dir: Path) -> bool:
    """A token resolves if it exists relative to the CWD (repo root) or to the adr-dir's
    parent-of-parent (the repo root when adr-dir is docs/adrs)."""
    return Path(token).exists() or (adr_dir.parent.parent / token).exists()


def check_adr(path: Path, adr_dir: Path) -> tuple[list[str], str]:
    """Errors for one ADR file + its verdict: "unparsed" (no `**Status:**` header — the gate
    can't see it), "skipped" (not Accepted — not gated), "traced" (a Research path resolves),
    or "waived" (explicit waiver)."""
    header = parse_header(path.read_text(encoding="utf-8"))
    try:
        rel = path.relative_to(adr_dir)
    except ValueError:
        rel = path

    status = header.get("Status")
    if status is None:
        return [], "unparsed"  # legacy Status shape — feeds the vacuous-pass warning, not gated
    if "accepted" not in status.lower():
        # Case-insensitive: `**Status:** accepted` (legacy lowercase) is a real acceptance and
        # MUST be gated — silently skipping it was a correctness hole (a live decision escaped
        # the trace gate). Proposed/Rejected/Superseded still pass untouched.
        return [], "skipped"

    research = header.get("Research")
    if research is None:
        return [f"{rel}: Accepted but no **Research:** line — {FIX_HINT}"], "traced"

    if "waiver:" in research.lower():
        return [], "waived"  # explicit waiver — passes, reported in the summary

    value = research.strip()
    if value in _BARE_DASH:
        return [f"{rel}: Accepted but Research is a bare dash/empty — {FIX_HINT}"], "traced"
    if "{{" in value:
        return [f"{rel}: Accepted but Research is an unfilled placeholder — {FIX_HINT}"], "traced"

    tokens = path_tokens(value)
    if not tokens:
        return [f"{rel}: Accepted but Research names no path — {FIX_HINT}"], "traced"
    if not any(_resolves(t, adr_dir) for t in tokens):
        return [
            f"{rel}: Accepted but no Research path resolves on disk "
            f"({', '.join(repr(t) for t in tokens)}) — {FIX_HINT}"
        ], "traced"
    return [], "traced"


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) > 1:
        print("usage: adr_trace_check.py [<adr-dir>]", file=sys.stderr)
        return 2
    adr_dir = Path(argv[0] if argv else DEFAULT_ADR_DIR)
    if not adr_dir.is_dir():
        print(f"not a directory: {adr_dir}", file=sys.stderr)
        return 2

    adrs = iter_adr_files(adr_dir)
    errors: list[str] = []
    unparsed: list[str] = []
    accepted = waived = 0
    for adr in adrs:
        errs, verdict = check_adr(adr, adr_dir)
        errors.extend(errs)
        if verdict in ("traced", "waived"):
            accepted += 1
        if verdict == "waived":
            waived += 1
        if verdict == "unparsed":
            unparsed.append(adr.name)

    if errors:
        print(f"✗ adr-trace check failed ({len(errors)} issue(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    summary = f"{len(adrs)} ADR(s): {accepted} accepted, {waived} waived"
    if unparsed:
        summary += f", {len(unparsed)} unparsed-status"
    print(f"✓ adr-trace check passed ({summary})")
    if unparsed:
        scope = (
            "VACUOUS PASS — ALL"
            if len(unparsed) == len(adrs)
            else f"{len(unparsed)} of {len(adrs)}"
        )
        print(
            f"⚠ adr-trace: {scope} ADR(s) carry no parseable **Status:** header — the trace "
            f"gate cannot see them. Author new ADRs from _template.md, or add a "
            f"`**Status:**` line to gate legacy ADRs:",
            file=sys.stderr,
        )
        for name in unparsed[:10]:
            print(f"  - {name}", file=sys.stderr)
        if len(unparsed) > 10:
            print(f"  … and {len(unparsed) - 10} more", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

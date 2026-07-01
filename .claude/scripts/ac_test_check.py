#!/usr/bin/env python3
"""Machine-check the criterion->test forcing function (the AC<->test map).

Don't claim "every AC is covered" by eyeball — that is how vacuous tests pass (UTBoost). This
parses acceptance-criterion ids (`AC-N`) from a DEFINE.md / spec and the AC ids the test suite
references, and FAILS when the map has a hole: an AC with no test, or a test pointing at an AC
that doesn't exist. It is the buildable-now slice of the output-quality evaluator (ADR-0014
step 2) — mechanical, no LLM-judge calibration needed.

Stdlib-only. Language-light: it matches `AC-<n>` ids by regex, so it works for any test
framework as long as each test names the AC it covers (a docstring tag or the test name).

Phase-safe (AC ids are numbered per-phase from zero). A shared `tests/` tree holds many phases'
tests, so a bare tree scan would flag another phase's `AC-5` as an orphan of THIS phase. Two
mechanisms keep the check scoped to the phase (import the id/file model from validity_lib so
the ac-green anchor agrees):
  - qualified ids — `AC-S04P1-3` carries a phase namespace; the orphan check only considers
    referenced ids in a namespace THIS source declares, so foreign ids are ignored, not flagged.
  - `--include <glob>` (repeatable) — scan only the files matching the glob(s), i.e. this
    phase's tests. Use it when phases share a flat tree with unqualified ids.
With neither flag and plain ids, behaviour is exactly as before (single-phase compatible).

Fails (exit 1) when:
  - an AC id declared in the source has no referencing test (uncovered criterion);
  - a test references an AC id in a namespace the source declares but that exact id is not
    declared (orphan / drifted reference — within the phase, foreign phases excluded);
  - (with --security) a security-critical AC (🔒 in the source) has no `[adversarial]`-tagged
    test. A happy-path test for a tenant-isolation / authz AC passes trivially while the real
    abuse vectors leak; the adversarial tag forces a negative/abuse test to exist.

Usage:
    python ac_test_check.py <acs-source: DEFINE.md|spec.md> <tests-root> [--security] \
        [--include <glob> ...]

Conventions for --security:
  - Mark a security AC by putting 🔒 on its line in the source (e.g. `AC-3 🔒 …`).
  - Mark an adversarial test by putting `[adversarial]` (or the word `adversarial`) on the
    same line as — or within 3 lines of — its `AC-N` tag (test name or docstring).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import validity_lib as v

AC_RE = v.AC_RE
ADVERSARIAL_RE = re.compile(r"\[adversarial\]|\badversarial\b", re.IGNORECASE)
LOCK = "🔒"
ADJACENCY = 3  # lines a `[adversarial]` marker may sit from its AC tag and still bind
TEST_GLOBS = v.TEST_GLOBS  # single SSoT of "what is a test file" (validity_lib)

ids_in = v.ids_in


def security_ids_in(text: str) -> set[str]:
    """AC ids whose source line carries the 🔒 lock marker."""
    out: set[str] = set()
    for line in text.splitlines():
        if LOCK in line:
            out |= ids_in(line)
    return out


def adversarial_ids_in(text: str) -> set[str]:
    """AC ids tagged adversarial — an `[adversarial]`/`adversarial` marker within ADJACENCY
    lines of the AC tag (same line, or its docstring just above/below)."""
    lines = text.splitlines()
    adv_lines = [i for i, ln in enumerate(lines) if ADVERSARIAL_RE.search(ln)]
    out: set[str] = set()
    for i in adv_lines:
        lo = max(0, i - ADJACENCY)
        hi = min(len(lines), i + ADJACENCY + 1)
        for ln in lines[lo:hi]:
            out |= ids_in(ln)
    return out


def main() -> int:
    argv = sys.argv[1:]
    security = "--security" in argv
    argv = [a for a in argv if a != "--security"]
    include: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--include":
            if i + 1 >= len(argv):
                print("--include needs a glob argument", file=sys.stderr)
                return 2
            include.append(argv[i + 1])
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    argv = rest
    if len(argv) != 2:
        print(
            "usage: ac_test_check.py <acs-source> <tests-root> [--security] [--include <glob> ...]",
            file=sys.stderr,
        )
        return 2
    src = Path(argv[0])
    tests = Path(argv[1])
    if not src.is_file():
        print(f"not a file: {src}", file=sys.stderr)
        return 2
    if not tests.is_dir():
        print(f"not a directory: {tests}", file=sys.stderr)
        return 2

    src_text = src.read_text(encoding="utf-8")
    declared = ids_in(src_text)
    # A phase's criteria live in ONE namespace (its dominant one). Ids in another namespace are
    # cross-phase references in prose (`…asserted upstream by AC-P3-06`), not this phase's
    # criteria — exclude them so they neither demand coverage nor get flagged.
    own = v.own_namespace(declared)
    declared = {a for a in declared if v.ac_namespace(a) == own}
    security_acs = (security_ids_in(src_text) & declared) if security else set()
    if not declared:
        print(
            f"✗ no AC-N ids found in {src} — acceptance criteria must be tagged AC-1, AC-2, …",
            file=sys.stderr,
        )
        return 1

    referenced: set[str] = set()
    adversarial: set[str] = set()
    for f in v.iter_test_files(tests, include or None):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        referenced |= ids_in(text)
        if security:
            adversarial |= adversarial_ids_in(text)

    # Orphan check is namespace-scoped: only referenced ids in THIS phase's namespace can be
    # orphans. A foreign phase's `AC-5` (different/empty namespace) is ignored, not flagged —
    # that was the cross-phase false positive. Real drift within the phase (a ref to an
    # undeclared id in this namespace) is still caught. When phases share a flat tree with
    # unqualified ids, scope the scan with --include instead.
    in_scope = {a for a in referenced if v.ac_namespace(a) == own}
    uncovered = sorted(declared - referenced, key=v.ac_sort_key)
    orphan = sorted(in_scope - declared, key=v.ac_sort_key)
    unadversarial = sorted(security_acs - adversarial, key=v.ac_sort_key)

    errors: list[str] = []
    for ac in uncovered:
        errors.append(f"{ac}: declared in {src.name} but no test references it (uncovered criterion)")
    for ac in orphan:
        errors.append(f"{ac}: referenced by a test but not declared in {src.name} (orphan/drifted reference)")
    for ac in unadversarial:
        errors.append(
            f"{ac}: security-critical (🔒) but no [adversarial]-tagged test — a happy-path "
            f"test passes trivially while abuse vectors leak; add a fail-closed abuse test"
        )

    if errors:
        print(f"✗ AC<->test check failed ({len(errors)} issue(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    sec = f", {len(security_acs)} security-critical all adversarially covered" if security else ""
    print(f"✓ AC<->test check passed ({len(declared)} criteria, all covered{sec})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""eval-03 — the per-AC GREEN execution anchor (Sprint A1 / P-1; ADR-0014 §2 execution-first).

`ac_test_check.py` proves an AC has a test *referencing* it. This proves the test actually
**ran GREEN, was RED at phase start, and asserts non-trivially** — closing the vacuous-green
hole (a test that references AC-3 and passes while asserting nothing). Per declared AC it emits
one of:
  - `proven`   — a mapped test was RED at baseline, is GREEN now, and has >=1 non-trivial assert.
  - `fail`     — a mapped test fails now (with the test id).
  - `unproven` — no mapped test / didn't execute (skip/error) / green-but-never-RED / green-but-vacuous.

Never reports `proven` on weak evidence (fail-closed). Stdlib only.

AC ids are phase-scoped, so the AC->test map keys on the FULL id (plain / suffixed / qualified,
per validity_lib.AC_RE). A foreign phase's `AC-5` never maps onto this phase's `AC-S04P1-5`. For
a flat tree of unqualified ids, pass `--include <glob>` (repeatable) to scan only this phase's
tests — same scoping model as ac_test_check.

Usage:
    python ac_green_check.py <DEFINE.md> <green-junit.xml> <tests-dir> <red-baseline.json> \
        [--include <glob> ...] [--json out.json]
Exit 0 iff every declared AC is `proven`; else 1 (verbose).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import validity_lib as v


def evaluate_acs(define_text, green_junit, tests_dir, red_baseline, include=None):
    """Return {AC-id: {status, tests, evidence, red_then_green, assert_count}}."""
    declared = v.declared_acs(define_text)
    # A phase's criteria live in one namespace; a cross-phase reference in prose (another
    # namespace) is not something THIS phase must prove — exclude it, matching ac_test_check.
    own = v.own_namespace(declared)
    declared = {a for a in declared if v.ac_namespace(a) == own}
    acs_by_test = v.test_acs(tests_dir, include)         # {test_name: {AC ids}}
    asserts = v.assert_counts(tests_dir, include)        # {test_name: count}
    junit = v.parse_junit(green_junit)          # {test_name: status}
    baseline = {b["test_id"]: b for b in (red_baseline or [])}

    ac_to_tests: dict[str, list[str]] = {}
    for test_name, acs in acs_by_test.items():
        for ac in acs:
            ac_to_tests.setdefault(ac, []).append(test_name)

    out: dict[str, dict] = {}
    for ac in sorted(declared, key=v.ac_sort_key):
        mapped = sorted(ac_to_tests.get(ac, []))
        if not mapped:
            out[ac] = {"status": "unproven", "tests": [], "evidence": "no mapped test (uncovered)",
                       "red_then_green": False, "assert_count": 0}
            continue

        per: list[tuple[str, str, bool, int]] = []  # (test, state, was_red, asserts_now)
        for t in mapped:
            js = junit.get(t)
            was_red = bool(baseline.get(t, {}).get("was_red", False))
            a_now = int(asserts.get(t, 0))
            if js == "fail":
                state = "fail"
            elif js == "pass":
                state = "proven" if (was_red and a_now >= 1) else "unproven"
            else:  # None (not run / non-parseable), "skip", "error" -> did not execute
                state = "unproven"
            per.append((t, state, was_red, a_now))

        fails = [p for p in per if p[1] == "fail"]
        provens = [p for p in per if p[1] == "proven"]
        if fails:
            t, _, _, a = fails[0]
            out[ac] = {"status": "fail", "tests": mapped,
                       "evidence": f"{t} fails now ({green_junit if isinstance(green_junit,str) else Path(green_junit).name}::{t})",
                       "red_then_green": False, "assert_count": a}
        elif provens:
            t, _, _, a = provens[0]
            out[ac] = {"status": "proven", "tests": mapped,
                       "evidence": f"{t} (RED->GREEN, {a} non-trivial assert)",
                       "red_then_green": True, "assert_count": a}
        else:
            t, _, was_red, a = per[0]
            why = ("never RED at baseline" if not was_red else
                   "zero non-trivial assertions" if a < 1 else "did not execute (skip/error/not run)")
            out[ac] = {"status": "unproven", "tests": mapped,
                       "evidence": f"{t}: {why}", "red_then_green": False, "assert_count": a}
    return out


def main() -> int:
    argv = sys.argv[1:]
    json_out = None
    if "--json" in argv:
        i = argv.index("--json")
        json_out = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
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
    if len(argv) != 4:
        print("usage: ac_green_check.py <DEFINE.md> <green-junit.xml> <tests-dir> <red-baseline.json> "
              "[--include <glob> ...] [--json out.json]",
              file=sys.stderr)
        return 2
    define_p, junit_p, tests_p, base_p = (Path(a) for a in argv)
    define_text = define_p.read_text(encoding="utf-8") if define_p.is_file() else ""
    try:
        baseline = json.loads(Path(base_p).read_text(encoding="utf-8")) if base_p.is_file() else []
    except json.JSONDecodeError:
        baseline = []  # missing/corrupt baseline -> everything fail-closes to unproven
    res = evaluate_acs(define_text, junit_p, tests_p, baseline, include or None)
    if json_out is not None:
        json_out.write_text(json.dumps(res, indent=2), encoding="utf-8")

    if not res:
        print("✗ no AC-N ids declared in the DEFINE — nothing to prove", file=sys.stderr)
        return 1
    not_proven = {ac: r for ac, r in res.items() if r["status"] != "proven"}
    if not not_proven:
        print(f"✓ ac-green: all {len(res)} ACs proven (RED->GREEN, non-trivial)")
        return 0
    print(f"✗ ac-green: {len(not_proven)}/{len(res)} AC(s) not proven:", file=sys.stderr)
    for ac, r in sorted(not_proven.items(), key=lambda kv: v.ac_sort_key(kv[0])):
        print(f"  - {ac}: {r['status']} — {r['evidence']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

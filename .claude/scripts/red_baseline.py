#!/usr/bin/env python3
"""red_baseline — the phase-start RED snapshot, the shared input of AC-5 and AC-8 (Sprint A1 / P-1).

`phase-implement` runs this at impl-start (tests RED, before code) to record, per mapped test,
`{test_id, was_red, assert_count}` to `.red-baseline.json`. `ac_green_check` (AC-8) and
`diff_gate` (AC-5) read it. `baseline_health` enforces AC-9: an absent/incomplete/stale baseline
is surfaced so the consuming gate fail-closes those ACs to `unproven` (never `proven`).

Stdlib only. Assert counting is Python-AST (validity_lib); a non-Python suite gets no count,
so AC-5/AC-8 degrade to `unproven` — never a false `proven`.

Usage:
    python red_baseline.py <red-run-junit.xml> <tests-dir> [-o .red-baseline.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import validity_lib as v


def capture(red_junit, tests_dir) -> list[dict]:
    """Snapshot every current test: was_red at baseline (failed/errored) + non-trivial assert count."""
    status = v.parse_junit(red_junit)          # {test: pass|fail|error|skip}
    asserts = v.assert_counts(tests_dir)       # {test: count}
    out = []
    for test_id in sorted(asserts):
        out.append({
            "test_id": test_id,
            "was_red": status.get(test_id) in ("fail", "error"),
            "assert_count": int(asserts[test_id]),
        })
    return out


def baseline_health(baseline, tests_dir) -> dict:
    """AC-9: report present/complete/stale. `missing` tests will fail-close to unproven downstream."""
    current = set(v.assert_counts(tests_dir))
    have = {b.get("test_id") for b in (baseline or [])}
    missing = sorted(current - have)   # current tests with no baseline -> can't be proven
    extra = sorted(have - current)     # baseline entries for gone tests -> stale
    return {
        "present": bool(baseline),
        "complete": bool(baseline) and not missing,
        "stale": bool(extra),
        "missing": missing,
        "extra": extra,
    }


def main() -> int:
    argv = sys.argv[1:]
    out_path = Path(".red-baseline.json")
    if "-o" in argv:
        i = argv.index("-o")
        out_path = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 2:
        print("usage: red_baseline.py <red-run-junit.xml> <tests-dir> [-o out.json]", file=sys.stderr)
        return 2
    junit, tests = Path(argv[0]), Path(argv[1])
    base = capture(junit, tests)
    out_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    reds = sum(1 for b in base if b["was_red"])
    print(f"✓ red-baseline: {len(base)} tests captured ({reds} RED) → {out_path}")
    if reds == 0 and base:
        print("⚠ no test was RED at baseline — a RED→GREEN transition can't be proven (AC-8 will be unproven)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

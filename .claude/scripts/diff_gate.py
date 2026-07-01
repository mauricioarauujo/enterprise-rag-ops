#!/usr/bin/env python3
"""loop-02 — the deterministic scope/test-immutability gate (Sprint A1 / P-1).

Makes two prose invariants of the Implement Contract mechanical:
  - AC-4 (no scope creep): a changed file absent from the phase DESIGN file-manifest is flagged.
  - AC-5 (no test weakening): a mapped test whose non-trivial assert-count dropped vs its
    phase-start RED baseline is flagged (a deleted test -> count 0 is the ultimate weakening).

Read-only; never executes diff content; stdlib only. "Trust the gate, not the checker."

Usage:
    python diff_gate.py <manifest.txt> <changed.txt> <red-baseline.json> <tests-dir>
  (manifest.txt / changed.txt = one path per line; dir entries end with '/'.)
Exit 0 iff no out-of-manifest files and no weakened tests; else 1 (verbose).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import validity_lib as v


def _covered(path: str, manifest: list[str]) -> bool:
    for m in manifest:
        m = m.strip()
        if not m:
            continue
        base = m.rstrip("/")
        if path == base or path.startswith(base + "/"):
            return True
    return False


def evaluate_diff(manifest, changed, red_baseline, tests_dir):
    """Return {out_of_manifest: [paths], weakened_tests: [{id, baseline, now, delta}]}."""
    out_of_manifest = sorted(p for p in changed if p.strip() and not _covered(p.strip(), manifest))

    now_counts = v.assert_counts(tests_dir)
    weakened = []
    for b in (red_baseline or []):
        tid = b.get("test_id")
        if tid is None:
            continue
        base = int(b.get("assert_count", 0))
        now = int(now_counts.get(tid, 0))
        if now < base:
            weakened.append({"id": tid, "baseline": base, "now": now, "delta": now - base})
    weakened.sort(key=lambda w: w["id"])
    return {"out_of_manifest": out_of_manifest, "weakened_tests": weakened}


def _lines(p: Path) -> list[str]:
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.is_file() else []


def main() -> int:
    argv = sys.argv[1:]
    json_out = None
    if "--json" in argv:
        i = argv.index("--json")
        json_out = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 4:
        print("usage: diff_gate.py <manifest.txt> <changed.txt> <red-baseline.json> <tests-dir> [--json out.json]",
              file=sys.stderr)
        return 2
    manifest_p, changed_p, base_p, tests_p = (Path(a) for a in argv)
    try:
        baseline = json.loads(base_p.read_text(encoding="utf-8")) if base_p.is_file() else []
    except json.JSONDecodeError:
        baseline = []
    res = evaluate_diff(_lines(manifest_p), _lines(changed_p), baseline, tests_p)
    if json_out is not None:
        json_out.write_text(json.dumps(res, indent=2), encoding="utf-8")

    flags = res["out_of_manifest"] or res["weakened_tests"]
    if not flags:
        print("✓ diff-gate: no scope-creep, no test-weakening")
        return 0
    print("✗ diff-gate: violations", file=sys.stderr)
    for p in res["out_of_manifest"]:
        print(f"  - out-of-manifest (scope creep): {p}", file=sys.stderr)
    for w in res["weakened_tests"]:
        print(f"  - test-weakening: {w['id']} asserts {w['baseline']}->{w['now']} (delta {w['delta']})",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

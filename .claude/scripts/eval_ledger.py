#!/usr/bin/env python3
"""eval_ledger — the eval-04 calibration scorer (Sprint B1 / P-1; ADR-0014 step 8 "calibrate
before gating").

Scores the evaluator against an injected-failure ground-truth ledger: per risk tier (AC-18,
never pooled), as BOTH TPR (injected faults the evaluator flagged) AND TNR (clean controls it
did NOT false-flag), on a dev / held-out split reported separately (AC-19). Read against the
evaluator's own blast-radius-scaled ADVISORY bars (R1≥0.80 · R2≥0.85 · R3≥0.90) — these are
advisory, NEVER a blocking CI gate (ADR-0014 refutes the end-to-end eval gate; the build is
"done" when the script REPORTS the numbers, not when they clear a threshold).

A criterion is "flagged" iff the evaluator's emitted status != "pass" (fail OR needs-decision —
both mean "did not clear", honouring each fault's `expected_not: status != pass`). Stdlib only.

  validate_entry(entry) -> [problems]            # AC-15 format check
  score(ledger, actual)  -> {tier: {split: {...}}}   # AC-16/17/18/19
  render_report(scores)  -> str                  # the per-tier advisory report
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED = ("fault_id", "risk_tier", "target_criterion", "ground_truth_verdict")
TIERS = ("R1", "R2", "R3")
ADVISORY_BARS = {"R1": 0.80, "R2": 0.85, "R3": 0.90}  # blast-radius-scaled; R3 strictest


def validate_entry(entry: dict) -> list[str]:
    """Return a list of problems (empty == valid). AC-15: each entry must carry the required fields
    and a ground_truth_verdict of pass|fail; a malformed entry is rejected, never scored blind."""
    problems = []
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    for f in REQUIRED:
        if not entry.get(f):
            problems.append(f"missing required field: {f}")
    gt = entry.get("ground_truth_verdict")
    if gt not in ("pass", "fail"):
        problems.append(f"ground_truth_verdict must be pass|fail, got {gt!r}")
    if entry.get("risk_tier") and entry["risk_tier"] not in TIERS:
        problems.append(f"risk_tier must be one of {TIERS}, got {entry['risk_tier']!r}")
    return problems


def _flagged(status: str) -> bool:
    """The evaluator 'flagged' a unit iff it did not clear it (anything but an explicit pass)."""
    return status != "pass"


def score(ledger: list[dict], actual: dict[str, str]) -> dict:
    """Compute per-tier, per-split TPR & TNR. `actual` maps fault_id -> the evaluator's emitted
    status (pass|fail|needs-decision). Tiers are never pooled (AC-18); splits are kept separate
    (AC-19). A fault with no actual verdict fail-closes to 'missed' for TPR (never silently
    credited)."""
    cells: dict = {}
    for entry in ledger:
        if validate_entry(entry):
            continue  # malformed entries are excluded from the score (and surfaced upstream)
        tier = entry["risk_tier"]
        split = entry.get("split", "dev")
        cell = cells.setdefault(tier, {}).setdefault(split, {
            "tpr": None, "tnr": None, "n_faults": 0, "n_controls": 0,
            "caught": 0, "passed_controls": 0, "missed_faults": [], "false_flags": [],
        })
        fid = entry["fault_id"]
        emitted = actual.get(fid)  # None if the evaluator produced nothing for this scenario
        gt = entry["ground_truth_verdict"]
        if gt == "fail":  # an injected fault — the evaluator SHOULD flag it
            cell["n_faults"] += 1
            if emitted is not None and _flagged(emitted):
                cell["caught"] += 1
            else:
                cell["missed_faults"].append(fid)  # cleared OR no verdict → missed (fail-closed)
        else:  # a clean control — the evaluator should NOT flag it
            cell["n_controls"] += 1
            if emitted == "pass":
                cell["passed_controls"] += 1
            else:
                cell["false_flags"].append(fid)
    # finalise rates
    for tier in cells:
        for split, c in cells[tier].items():
            c["tpr"] = round(c["caught"] / c["n_faults"], 4) if c["n_faults"] else None
            c["tnr"] = round(c["passed_controls"] / c["n_controls"], 4) if c["n_controls"] else None
    return cells


def render_report(scores: dict) -> str:
    lines = ["# EVAL CALIBRATION — advisory per-tier accuracy (ADR-0014 step 8)", "",
             "_Advisory bars (NOT a blocking gate): R1≥0.80 · R2≥0.85 · R3≥0.90 (R3 strictest)._",
             "", "| tier | split | TPR (faults caught) | TNR (clean kept) | bar | reads |",
             "| --- | --- | --- | --- | --- | --- |"]
    for tier in sorted(scores):
        bar = ADVISORY_BARS.get(tier)
        for split in sorted(scores[tier]):
            c = scores[tier][split]
            tpr, tnr = c["tpr"], c["tnr"]
            if tpr is None or tnr is None:
                # AC-18 needs BOTH; a half-measured tier is not calibrated (M3) — never "trust".
                reads = "INCOMPLETE — TPR ∧ TNR both required (seed faults AND clean controls)"
            elif tpr >= bar and tnr >= bar:
                reads = "≥ bar (trust as advisory)"
            else:
                reads = "BELOW bar — keep the human reading closely"
            lines.append(f"| {tier} | {split} | {tpr} ({c['caught']}/{c['n_faults']}) | "
                         f"{tnr} ({c['passed_controls']}/{c['n_controls']}) | {bar} | {reads} |")
    missed = [(t, s, f) for t in scores for s in scores[t] for f in scores[t][s]["missed_faults"]]
    if missed:
        lines += ["", "**Missed faults (false-negatives — the dangerous ones):**"]
        lines += [f"- {t}/{s}: `{f}`" for t, s, f in missed]
    return "\n".join(lines) + "\n"


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) < 2:
        print("usage: eval_ledger.py <ledger.json> <actual-verdicts.json>", file=sys.stderr)
        return 2
    ledger = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    actual = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    if not isinstance(ledger, list):
        print("✗ ledger must be a JSON array of entries (see ledger.schema.json)", file=sys.stderr)
        return 2
    problems = [f"{(e.get('fault_id', '?') if isinstance(e, dict) else '?')}: {p}"
                for e in ledger for p in validate_entry(e)]
    if problems:
        print("✗ ledger has malformed entries (excluded from the score):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
    print(render_report(score(ledger, actual)))
    return 0  # advisory — reporting the numbers IS the build's done-condition, never a gate


if __name__ == "__main__":
    raise SystemExit(main())

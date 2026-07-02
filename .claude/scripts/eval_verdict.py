#!/usr/bin/env python3
"""eval_verdict — the end-to-end deterministic verdict assembler (Sprint B1 / P-1; ADR-0014).

The sibling of `validity_artifact.py`, for output-quality. Composes:
  - the eval-03 ac-green ledger (executable criteria)            -> exec status
  - the judge-result (non-executable criteria ONLY)             -> judge status
  - the risk-tier map (per-AC R1/R2/R3 + severity)
  - the provenance stamp (maker≠checker, AC-13)
into ONE `EVAL.json` (SSoT) + `EVAL.md` (rendered from it). Every fail-closed / maker≠checker
decision is computed in `eval_lib`/`provenance` — the LLM judge only contributes raw verdicts as
data and can never flip an executable criterion (AC-2) or manufacture a clear (AC-13).

Usage:
    eval_verdict.py --ac ac.json --judge judge.json --tiers tiers.json \
        --provenance .provenance.json --evaluator-id <id> [--nonces consumed.json] [-o EVAL]
Exit 0 iff verdict == "clear".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import eval_lib as e
import provenance as prov


def _load(path, default):
    p = Path(path)
    if not p or not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return default


def _as_dict(x):
    return x if isinstance(x, dict) else {}   # N2: a top-level non-dict input file → fail-closed


def assemble(ac_ledger_path, judge_path, tiers_path, provenance_path,
             evaluator_id, consumed_nonces=None, expected_generator_id=None) -> dict:
    """Build the verdict object from the four input files. Pure of IO side effects beyond reads."""
    ledger = _as_dict(_load(ac_ledger_path, {}))
    judge = _as_dict(_load(judge_path, {}))
    tiers = _as_dict(_load(tiers_path, {}))
    stamp = prov.read_stamp(provenance_path)
    prov_result = prov.verify(stamp, evaluator_id, consumed_nonces or set(), expected_generator_id)

    # Declared ACs = the risk-tier map's keys (every AC must carry a tier); fall back to the
    # union of the evidence sources so a tier-map gap can't silently drop a criterion.
    declared = set(tiers) | set(ledger) | set(judge)

    criteria = []
    for ac in declared:
        method = e.route(ac, ledger)
        if method == "exec":
            status, evidence = e.exec_status(ledger.get(ac, {}))   # AC-2: judge[ac] is ignored here
        else:
            status, evidence = e.judge_status(judge.get(ac))
        tinfo = tiers.get(ac)
        tinfo = tinfo if isinstance(tinfo, dict) else {}   # M2: malformed tier entry → fail-closed
        tier = tinfo.get("risk_tier")                       # None → finalize_criterion coerces to R3
        severity = tinfo.get("context_severity", "normal")
        criteria.append(e.finalize_criterion({
            "id": ac, "method": method, "status": status, "evidence": evidence,
            "risk_tier": tier, "context_severity": severity,
        }))

    return e.build_object(criteria, prov_result, evaluator_id)


def run(ac_ledger_path, judge_path, tiers_path, provenance_path, evaluator_id,
        out_stem=Path("EVAL"), expected_generator_id=None) -> int:
    """Advisory grade — IDEMPOTENT (N3): re-grading the same work is expected (you re-run /eval
    after fixes) and produces the same verdict. The nonce is NOT consumed here; single-use replay
    defense belongs to the R3 auto-action opt-in (`provenance.verify_optin`, AC-12, Phase C), where
    a stamp/opt-in actually authorizes an irreversible action — not to an advisory read."""
    obj = assemble(ac_ledger_path, judge_path, tiers_path, provenance_path, evaluator_id,
                   expected_generator_id=expected_generator_id)
    out_stem = Path(out_stem)
    out_stem.with_suffix(".json").write_text(json.dumps(obj, indent=2), encoding="utf-8")
    out_stem.with_suffix(".md").write_text(e.render_md(obj), encoding="utf-8")
    ok = obj["verdict"] == "clear"
    print(f"{'✓' if ok else '⚠'} eval: {obj['verdict']} → {out_stem}.json / {out_stem}.md")
    return 0 if ok else 1


def main() -> int:
    argv = sys.argv[1:]

    def opt(flag, required=True, default=None):
        if flag in argv:
            i = argv.index(flag)
            return argv[i + 1]
        if required:
            print(f"missing {flag}", file=sys.stderr); raise SystemExit(2)
        return default

    try:
        ac = opt("--ac"); judge = opt("--judge", required=False, default="/dev/null")
        tiers = opt("--tiers"); provenance = opt("--provenance")
        evaluator_id = opt("--evaluator-id")
        expected_gid = opt("--expected-generator-id", required=False)
        out = opt("-o", required=False, default="EVAL")
    except SystemExit:
        print("usage: eval_verdict.py --ac ac.json --judge judge.json --tiers tiers.json "
              "--provenance .provenance.json --evaluator-id <id> "
              "[--expected-generator-id <maker-id>] [-o EVAL]",
              file=sys.stderr)
        return 2
    return run(ac, judge, tiers, provenance, evaluator_id, Path(out),
               expected_generator_id=expected_gid)


if __name__ == "__main__":
    raise SystemExit(main())

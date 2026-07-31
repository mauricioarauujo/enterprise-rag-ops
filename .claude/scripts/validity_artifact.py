#!/usr/bin/env python3
"""validity_artifact — merge eval-03 + loop-02 into the machine-validity SSoT (Sprint A1 / P-1).

AC-6: when every AC is `proven` AND there are zero scope/weakening flags, emit ONE artifact —
`VALIDITY.json` (the SSoT) + `VALIDITY.md` (rendered from it, the phone-review block).
AC-7: the artifact labels its scope **tests + scope/immutability only — NOT output-quality / eval
verdicts**, so the human review can't over-claim validity (that judgment is Phase-2 `/eval`).

Stdlib only. JSON is the source of truth; markdown is one rendering of it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import validity_lib as v  # the AC id model — same SSoT ac_test_check/ac_green_check order by

SCOPE_LABEL = ("tests + scope/immutability only — NOT output-quality / eval verdicts "
               "(output-quality is Phase-2 /eval, ADR-0014)")


def build_artifact(ac_results: dict, diff_results: dict) -> dict:
    all_proven = bool(ac_results) and all(r.get("status") == "proven" for r in ac_results.values())
    clean = not (diff_results.get("out_of_manifest") or diff_results.get("weakened_tests"))
    return {
        "scope": SCOPE_LABEL,
        "all_proven": all_proven,
        "clean": clean,
        "verdict": "PASS" if (all_proven and clean) else "BLOCKED",
        "acs": ac_results,
        "diff": diff_results,
    }


def render_md(artifact: dict) -> str:
    lines = [f"# VALIDITY — {artifact['verdict']}",
             "",
             f"_Scope: {artifact['scope']}._",
             "",
             "| AC | status | evidence |",
             "| --- | --- | --- |"]
    # `ac_sort_key` is the shared helper every other AC-ordering call site already uses
    # (ac_test_check, ac_green_check). This was the last raw `int(ac.split('-')[1])` in the
    # product and it raised ValueError on any id with a letter suffix — `AC-3a` — which is
    # precisely the shape ac_sort_key exists to order. Found by a consumer that had already
    # fixed it locally.
    for ac, r in sorted(artifact["acs"].items(), key=lambda kv: v.ac_sort_key(kv[0])):
        lines.append(f"| {ac} | {r.get('status')} | {r.get('evidence', '')} |")
    d = artifact["diff"]
    lines += ["",
              f"**Scope/immutability gate:** out-of-manifest {len(d.get('out_of_manifest', []))} · "
              f"weakened tests {len(d.get('weakened_tests', []))}"]
    for p in d.get("out_of_manifest", []):
        lines.append(f"- ⚠ out-of-manifest (scope creep): `{p}`")
    for w in d.get("weakened_tests", []):
        lines.append(f"- ⚠ test-weakening: `{w['id']}` asserts {w.get('baseline')}→{w.get('now')}")
    return "\n".join(lines) + "\n"


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) < 2:
        print("usage: validity_artifact.py <ac-results.json> <diff-results.json> [-o VALIDITY]",
              file=sys.stderr)
        return 2
    out_stem = Path("VALIDITY")
    if "-o" in argv:
        i = argv.index("-o")
        out_stem = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    ac_results = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    diff_results = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    art = build_artifact(ac_results, diff_results)
    out_stem.with_suffix(".json").write_text(json.dumps(art, indent=2), encoding="utf-8")
    out_stem.with_suffix(".md").write_text(render_md(art), encoding="utf-8")
    print(f"{'✓' if art['verdict'] == 'PASS' else '✗'} validity: {art['verdict']} "
          f"→ {out_stem}.json / {out_stem}.md")
    return 0 if art["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

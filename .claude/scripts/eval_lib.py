#!/usr/bin/env python3
"""eval_lib — deterministic output-quality verdict helpers (Sprint B1 / P-1; ADR-0014).

The robustness seam (DESIGN §1.1): the LLM judge produces only *raw advisory verdicts as data*;
every fail-closed / schema-integrity / maker≠checker decision is computed HERE, in stdlib code,
so a prompt-injection or a forged id can never manufacture a `pass`.

  route(ac, ac_green_ledger) -> "exec" | "judge"        # AC-1/2 (executable iff mapped test)
  exec_status(entry)  -> (status, evidence)             # AC-8 (unproven→needs-decision)
  judge_status(raw)   -> (status, evidence)             # AC-8 (uncertain/absent→needs-decision)
  finalize_criterion(c) -> dict                         # AC-7 R3 deny-default, AC-11, AC-14
  build_object(criteria, provenance_result, evaluator_id) -> dict   # AC-4/6/10/13 + rollup
  render_md(obj) -> str                                 # AC-5 (success silent, failures verbose)

No LLM, no network. JSON object is the SSoT; markdown is one rendering of it.
"""
from __future__ import annotations

SCHEMA_VERSION = "eval/1"
SCOPE_LABEL = "output-quality (ADR-0014) — advisory; the human gates"
_STATUSES = {"pass", "fail", "needs-decision"}
_METHODS = {"exec", "judge"}


def _blank(x) -> bool:
    return not isinstance(x, str) or not x.strip()


# ── routing (AC-1/AC-2) ─────────────────────────────────────────────────────────
def route(ac: str, ac_green_ledger: dict) -> str:
    """Executable iff the eval-03 ledger has a non-empty mapped-test entry for this AC.
    Deterministic — the judge is never an option for an AC with a runnable test (AC-2)."""
    entry = (ac_green_ledger or {}).get(ac)
    if isinstance(entry, dict) and entry.get("tests"):   # non-dict entry → judge (M2, no crash)
        return "exec"
    return "judge"


def exec_status(entry: dict) -> tuple[str, str]:
    """Map an eval-03 ledger entry to a verdict status, fail-closed (AC-8): only `proven`
    becomes `pass`; `unproven` (uncovered/vacuous/never-RED/didn't-run) → needs-decision."""
    entry = entry if isinstance(entry, dict) else {}   # M2: non-dict → fail-closed, no crash
    st = entry.get("status")
    ev = entry.get("evidence", "")
    if st == "proven":
        return "pass", ev
    if st == "fail":
        return "fail", ev
    return "needs-decision", ev or "unproven"


def judge_status(raw: dict | None) -> tuple[str, str]:
    """Map a raw judge verdict to a status, fail-closed (AC-8): anything but an explicit
    pass/fail (uncertain, missing, malformed) → needs-decision; never a default pass."""
    raw = raw if isinstance(raw, dict) else {}   # M2: non-dict → fail-closed, no crash
    rv = raw.get("raw_verdict")
    quote = raw.get("evidence_quote", "")
    if rv == "pass":
        return "pass", quote
    if rv == "fail":
        return "fail", quote
    return "needs-decision", quote or "judge uncertain"


# ── per-criterion fail-closed finalize (AC-7/8/11/14) ───────────────────────────
def finalize_criterion(c: dict) -> dict:
    """Apply the fail-closed rules to one criterion and return its canonical verdict entry.
    AC-14: missing method/evidence → needs-decision. AC-7: R3 deny-by-default (a pass needs
    affirmative evidence). AC-11: R3 is never auto_clear_eligible."""
    cid = c.get("id")
    method = c.get("method")
    status = c.get("status")
    evidence = c.get("evidence")
    severity = c.get("context_severity", "normal")

    # Canonicalize the tier, FAIL-CLOSED (C1): a missing / blank / mis-cased / descriptive /
    # unknown tier coerces to the MOST RESTRICTIVE R3 — a mislabeled R3 surface must never be
    # treated as a lower tier and slip past the R3 protections.
    t = c.get("risk_tier")
    tier = t.strip().upper() if isinstance(t, str) and t.strip() else "R3"
    if tier not in ("R1", "R2", "R3"):
        tier = "R3"

    # AC-14: structurally broken → needs-decision (never pass).
    if method not in _METHODS or _blank(evidence):
        status = "needs-decision"
    # unknown/garbage status → fail-closed.
    if status not in _STATUSES:
        status = "needs-decision"
    # AC-7 (R3 deny-by-default, hardened per H2): an R3 criterion clears ONLY on EXECUTION proof.
    # A judge 'pass' (the prompt-injection / language-biased surface) is not affirmative proof of a
    # guarded invariant → needs-decision. This also covers blank evidence.
    if tier == "R3" and status == "pass" and (method != "exec" or _blank(evidence)):
        status = "needs-decision"

    # AC-11: R3 never auto-clears; and auto-clear is OPT-IN — only an EXPLICIT R1 pass is eligible
    # (so an unknown tier, coerced to R3, can never be auto-clearable).
    auto_clear_eligible = (tier == "R1" and status == "pass")
    return {
        "id": cid,
        "method": method if method in _METHODS else None,
        "status": status,
        "evidence": evidence if not _blank(evidence) else "(no evidence — fail-closed)",
        "risk_tier": tier,
        "context_severity": severity,
        "auto_clear_eligible": auto_clear_eligible,
    }


# ── object assembly (AC-4/6/10/13) ──────────────────────────────────────────────
def build_object(criteria: list[dict], provenance_result: dict, evaluator_id: str) -> dict:
    """Assemble the one verdict object (SSoT). AC-6: factorized, NO global score. AC-10:
    advisory_only always true. AC-13: a failed provenance check fail-closes the whole verdict
    to needs-human regardless of the criteria."""
    crit_map = {c["id"]: c for c in criteria}
    prov_ok = bool((provenance_result or {}).get("ok"))

    if not prov_ok:
        verdict = "needs-human"
    else:
        verdict = "clear" if crit_map and all(c["status"] == "pass" for c in crit_map.values()) \
            else "needs-human"

    obj = {
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE_LABEL,
        "generator_id": (provenance_result or {}).get("generator_id"),
        "evaluator_id": evaluator_id,
        "advisory_only": True,          # AC-10 — never blocks, never auto-approves
        "verdict": verdict,             # clear | needs-human (never auto-relaxes a gate)
        "criteria": crit_map,           # AC-6 — per-criterion; no holistic score key anywhere
    }
    if not prov_ok:
        obj["provenance_denied"] = (provenance_result or {}).get("reason", "unknown")
    return obj


# ── render (AC-5) ───────────────────────────────────────────────────────────────
def render_md(obj: dict) -> str:
    """Render EVAL.md FROM the object (never hand-authored). Success silent, failures verbose."""
    verdict = obj.get("verdict", "needs-human")
    lines = [f"# EVAL — {verdict}", "", f"_Scope: {obj.get('scope', '')}._",
             f"_advisory_only: {obj.get('advisory_only')} · generator_id: "
             f"{obj.get('generator_id')} · evaluator_id: {obj.get('evaluator_id')}._", ""]
    if obj.get("provenance_denied"):
        lines += [f"> ⛔ **maker≠checker DENIED** — provenance `{obj['provenance_denied']}`; "
                  f"verdict fail-closed to needs-human (no criterion can clear).", ""]
    lines += ["| AC | tier | method | status | auto-clear | evidence |",
              "| --- | --- | --- | --- | --- | --- |"]
    for ac, c in sorted(obj.get("criteria", {}).items(), key=lambda kv: _acnum(kv[0])):
        mark = "" if c["status"] == "pass" else "⚠ "
        lines.append(f"| {mark}{ac} | {c['risk_tier']} | {c.get('method')} | {c['status']} | "
                     f"{c['auto_clear_eligible']} | {c['evidence']} |")
    flagged = [ac for ac, c in obj.get("criteria", {}).items() if c["status"] != "pass"]
    if flagged:
        lines += ["", f"**Needs human:** {', '.join(sorted(flagged, key=_acnum))} "
                  f"(advisory — the human signs off; R3 never auto-clears)."]
    return "\n".join(lines) + "\n"


def _acnum(ac: str) -> int:
    try:
        return int(str(ac).split("-", 1)[1])
    except (IndexError, ValueError):
        return 9999

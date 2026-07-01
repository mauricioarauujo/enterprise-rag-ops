#!/usr/bin/env python3
"""provenance — the maker≠checker stamp (Sprint B1 / P-1; ADR-0014 §7, DESIGN §1.5).

`generator_id` must be unforgeable *by the graded artifact*. The mechanism is separation +
distinctness + single-use (tamper-evidence), NOT cryptography against a malicious operator of
the harness itself (that operator is the trusted founder — the same trust boundary as every
kbind gate). The implement flow writes the stamp at generation time with a `generator_id`
supplied by the harness invocation (never read from artifact content); `/eval` verifies it.

Every verify() / verify_optin() DENY path is **fail-closed**: a missing, blank, ambiguous, or
replayed input is NEVER accepted. Stdlib only, no LLM, no network.

  stamp(generator_id, git_head[, nonce, ts]) -> dict          # the implement-time stamp
  write_stamp(stamp, path) / read_stamp(path) -> dict | None   # IO at the phase dir
  verify(stamp, evaluator_id, consumed_nonces) -> result       # AC-13 maker≠checker
  verify_optin(optin, generator_id, action, consumed_nonces)   # AC-12 R3 carve-out

`result` = {"ok": bool, "reason": str, "generator_id": str | None}.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blank(x) -> bool:
    return not isinstance(x, str) or not x.strip()


def stamp(generator_id: str, git_head: str, nonce: str | None = None, ts: str | None = None) -> dict:
    """Build the implement-time provenance stamp. `generator_id` comes from the harness, never
    from artifact content. A fresh single-use `nonce` is generated unless one is supplied."""
    return {
        "generator_id": generator_id,
        "git_head": git_head,
        "nonce": nonce if nonce else uuid.uuid4().hex,
        "timestamp": ts if ts else _now_iso(),
    }


def write_stamp(stamp_obj: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(stamp_obj, indent=2), encoding="utf-8")


def read_stamp(path: str | Path) -> dict | None:
    """Read the stamp the implement flow wrote. Missing / unreadable / malformed → None
    (the caller fail-closes to DENY — a phase with no provenance is never auto-trusted)."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _deny(reason: str, gid=None) -> dict:
    return {"ok": False, "reason": reason, "generator_id": gid}


def verify(stamp_obj: dict | None, evaluator_id: str, consumed_nonces: set[str],
           expected_generator_id: str | None = None) -> dict:
    """AC-13 maker≠checker. ALLOW only when the stamp is present, carries a real `generator_id`,
    that id differs from the evaluator's own run, its nonce is present (and, if a consumed set is
    supplied, unreplayed), AND — when the harness supplies `expected_generator_id` out-of-band (the
    trusted invocation channel) — the stamp's id MATCHES it. The expected-id check closes the
    untrusted-maker vector: a graded agent that rewrites `.provenance.json` to a different id
    mismatches the harness's record → DENY. Anything else DENYs — a missing/blank/forged/replayed/
    mismatched input never yields ok=True."""
    if not stamp_obj or not isinstance(stamp_obj, dict):
        return _deny("absent")
    gid = stamp_obj.get("generator_id")
    if _blank(gid):
        return _deny("missing_generator_id")
    if _blank(evaluator_id):
        # Can't prove distinctness from a blank evaluator id → fail-closed.
        return _deny("missing_evaluator_id", gid)
    nonce = stamp_obj.get("nonce")
    if _blank(nonce):
        # No single-use material → the stamp could replay forever → fail-closed (H1).
        return _deny("missing_nonce", gid)
    if nonce in (consumed_nonces or set()):
        return _deny("replayed", gid)
    if gid.strip() == evaluator_id.strip():
        return _deny("self_grade", gid)
    # The harness pins the maker's identity out-of-band; a stamp that doesn't match it was not
    # written by the harness for this work → DENY (closes the untrusted-maker overwrite vector).
    if not _blank(expected_generator_id) and gid.strip() != expected_generator_id.strip():
        return _deny("generator_mismatch", gid)
    return {"ok": True, "reason": "ok", "generator_id": gid.strip()}


def verify_optin(optin: dict | None, generator_id: str, action: str,
                 consumed_nonces: set[str]) -> dict:
    """AC-12 — the sole R3 auto-action carve-out. ALLOW only a human-sourced, action-bound,
    single-use opt-in NOT issued by the work's own generating agent (or the artifact). Every
    other shape DENYs: this is the one path through R3-never-auto and must not be manufacturable
    by an injected/coerced/replayed token."""
    if not optin or not isinstance(optin, dict):
        return _deny("absent")
    if optin.get("source") != "human":
        return _deny("not_human")
    issuer = optin.get("issuer")
    if _blank(issuer):
        return _deny("missing_issuer")
    if issuer.strip() in {generator_id.strip() if isinstance(generator_id, str) else generator_id, "artifact"}:
        return _deny("issuer_is_generator")
    bound = optin.get("action_bound")
    if _blank(bound):
        # Must be bound to a concrete action — an unbound opt-in is transferable (fail-closed, M4).
        return _deny("missing_action_bound")
    if bound != action:
        return _deny("action_mismatch")
    nonce = optin.get("nonce")
    if _blank(nonce):
        return _deny("missing_nonce")
    if nonce in (consumed_nonces or set()):
        return _deny("replayed")
    return {"ok": True, "reason": "ok", "generator_id": None}


def main() -> int:
    """CLI: write a stamp. Used by phase-implement at generation time.
        provenance.py stamp <generator_id> <git_head> -o <path>"""
    argv = sys.argv[1:]
    if len(argv) >= 3 and argv[0] == "stamp":
        out = Path(".provenance.json")
        if "-o" in argv:
            i = argv.index("-o"); out = Path(argv[i + 1]); argv = argv[:i] + argv[i + 2:]
        gid, head = argv[1], argv[2]
        s = stamp(gid, head)
        write_stamp(s, out)
        print(f"✓ provenance: stamped generator_id={gid} head={head[:8]} → {out}")
        return 0
    print("usage: provenance.py stamp <generator_id> <git_head> [-o path]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

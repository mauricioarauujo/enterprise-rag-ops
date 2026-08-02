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
  - carries a GUARDRAILED waiver — a `waiver:` annotation that names a REASON and is DATED
    (in the annotation, or by the ADR's own `**Date:**` header), AND for which no research path
    resolves on disk. E.g. `**Research:** — (waiver: founder-call — ratified in-session
    2026-06-11)`. Waived ADRs are counted in the success summary ("N waived") so waivers stay
    visible — explicit beats silent, mirroring how check_spec_status treats `infra: true`.

    The guardrails exist because a waiver is the escape hatch on the gate that enforces the
    harness's leading claim, and an unguarded hatch is the whole gate. Until 2026-07-11 this was
    a bare substring test (`if "waiver:" in research`), evaluated BEFORE path resolution — so a
    reasonless, dateless `**Research:** waiver:` passed, and a waiver stamped over a real dossier
    was never checked against it. Ported from delivery-graph's `waiveNode` (evidence-engine.mjs),
    whose load-bearing rule is the second one: a waiver is only for what cannot be proven, so it
    is refused outright where the evidence exists.

    Deliberately NOT required: a separate machine-parsed `owner` field. Reason + date are the
    auditable minimum; a third positional field would be brittle phrase-matching against a live
    convention (the reason IS the owner today — "founder-call"), and phrase-pinning prose is the
    failure mode this check exists to replace.

Fails (exit 1) when an Accepted ADR has a bare "—", an empty/{{placeholder}} value, only
unresolvable paths, no `**Research:**` line at all, or a waiver that breaks either guardrail.
Skips `_template.md`, `README.md`, any `_*`-prefixed file, and `_archive/` trees; only
`NNNN-*.md` files are ADRs.

**Vacuous-pass guard (brownfield honesty).** An ADR with no parseable `**Status:**` header at
all (legacy shapes: `## Status` sections, MADR bullets — every brownfield predates the template
by construction) is invisible to this gate: it can neither be gated nor skipped-on-purpose. Those
files are counted as **unparsed-status** in the summary and a stderr warning names them, so a CI
gate that is green because it parsed nothing reads as VACUOUS instead of healthy. Exit stays 0 by
default — advisory-honest, not newly blocking (converge by authoring from `_template.md` or adding
a `**Status:**` line to legacy ADRs). **Under `--strict`, TOTAL blindness is an error**: a gate
that could not see one single ADR must not report success to the flag whose whole purpose is to
remove the escape hatch. Partial blindness keeps its N-of-M warning and is not this error.

Usage:
    python3 adr_trace_check.py [<adr-dir>]        # default: docs/adrs; exit 0/1/2
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

DEFAULT_ADR_DIR = "docs/adrs"  # layout-ok: the documented default, used only when no <adr-dir> arg
FIX_HINT = "add Research: <dossier path> or a reasoned, dated waiver (waiver: <reason> — <YYYY-MM-DD>)"

_ADR_NAME_RE = re.compile(r"^\d{4}-.*\.md$")
_HEADER_KEYS = ("Status", "Research", "Date", "Critique")

# ---------------------------------------------------------------------------------------------
# THE OBJECTION LEDGER (sprint E3a) — the adversarial-review half of the Accepted-ADR gate.
#
# `adr-critic` runs 6 checks and emits ✅/⚠️/❌ verdicts that were persisted NOWHERE, so an ADR
# could be Accepted, cite its research, pass this gate and pass CI with every ❌ silently dropped.
# "Resolve every ❌ (or own it explicitly)" was vocabulary without mechanism, at the rung the
# harness's leading claim is named after. The ledger is that mechanism: the critic's report is
# persisted at a DERIVED path, the ADR names it on a `**Critique:**` line, and every ❌ carries a
# disposition or the build fails.
#
# NOT HERE, BY RATIFIED DECISION (D84): there is no tamper-evidence digest. The same actor holds
# the ledger and the stamping tool and nothing forbids re-stamping, so a digest fires on
# formatters and on honest authors who forgot to re-run it, and never on an evader — inverted
# precision, to detect a one-character flip that `git diff` already shows through a mechanism the
# author cannot re-stamp. Do not add one back; it was the sole source of the byte-contract,
# VS16 and formatter-coupling surface.
# ---------------------------------------------------------------------------------------------

LEDGER_DIRNAME = "adr-critiques"  # layout-ok: a relative NAME, never a path; see ledger_path()
MIN_DISTINCT_OBJECTIONS = 6  # = adr-critic's check count, pinned by test_ac2_… reading the agent

VACUOUS_STATUS = "VACUOUS PASS"          # the shipped label: the gate could not SEE the ADRs
VACUOUS_CRITIQUE = "VACUOUS (critique)"  # it saw them, and not one carries a closed critique

# One `OBJ-N` heading per check. The tail is OPTIONAL (`.*`, not `.+`): a bare `### OBJ-7 ❌`
# must be SEEN and reported open, not fall out of the pattern and vanish — an unmatched heading
# is an undispositioned ❌ that escapes the gate entirely.
HEAD_RE = re.compile(
    r"^#{1,6}\s+OBJ-(?P<n>\d+)\s+(?P<verdict>❌|⚠|✅)️?\s*(?P<tail>.*)$"
)
# THE B2 FIX. v5 pinned `\((?P<body>.*)\)`, whose greedy `.*` runs to the LAST `)` on the line:
# `— ✅ FIXED (TBD) ()` yielded body='TBD) (' and read CLOSED, so two characters closed any ❌.
# `[^)]*` stops at the first `)` — and is the shape `_WAIVER_RE` above already uses, so the two
# escape hatches on this gate now read their bodies the same way.
# The `$` anchor stays OFF (v4's B1): an anchored form cannot absorb the trailing text in
# `— ✅ FIXED (§4) per review`, which is an honest disposition and false-RED'd for four revisions.
DISP_RE = re.compile(
    r"[—–-]\s*(?:✅️?\s*(?P<fixed>FIXED)|\U0001f513️?\s*(?P<accepted>ACCEPTED))"
    r"\s*\((?P<body>[^)]*)\)"
)
# A body that says nothing. `.strip()`-ed and matched whole, case-insensitively.
_DISP_BLOCKLIST_RE = re.compile(r"^(\{\{.*\}\}|TBD|TODO|N/?A|—|–|-|\?+)$", re.I)
# A fence ANYWHERE makes the ledger malformed — see the module docstring of the test file. One
# predicate, no divergence; tracking fences was the rule two honest readers exited differently on.
_FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")


class Objection(NamedTuple):
    id: int
    verdict: str  # "x" | "warn" | "ok"
    tail: str
    state: str  # "fixed" | "accepted" | "open"


def disposition_state(tail: str) -> str:
    """"fixed" / "accepted" / "open" for one objection heading's tail.

    FIRST match on the line wins, so an empty disposition cannot be laundered by appending a
    well-formed second one. `🔓 ACCEPTED` needs its reason AND its date IN THE BODY — there is
    deliberately no `**Date:**` header fallback, because all 16 workshop ADRs carry a `**Date:**`
    and an `or` would short-circuit every undated ownership into a pass. (The waiver keeps the
    header fallback: that is shipped `check_waiver` doctrine, not ours to relitigate.)
    """
    m = DISP_RE.search(tail)
    if not m:
        return "open"
    body = m.group("body").strip()
    if not body or _DISP_BLOCKLIST_RE.match(body):
        return "open"
    if m.group("accepted"):
        if not _LETTERS_RE.search(body) or not _DATE_RE.search(body):
            return "open"  # owning a defect needs a reason and a date it can age out from
        return "accepted"
    return "fixed"


def parse_objections(text: str) -> tuple[list[Objection], bool]:
    """(objections, contains_a_fence) for one ledger's text."""
    objections: list[Objection] = []
    fenced = False
    for raw in text.splitlines():
        if _FENCE_RE.match(raw):
            fenced = True
            continue
        m = HEAD_RE.match(raw.strip())
        if not m:
            continue
        verdict = {"❌": "x", "⚠": "warn", "✅": "ok"}[m.group("verdict")]
        tail = m.group("tail")
        objections.append(Objection(int(m.group("n")), verdict, tail, disposition_state(tail)))
    return objections, fenced


def ledger_path(adr_path: Path, adr_dir: Path) -> Path:
    """`<parent of the RESOLVED adrs dir>/adr-critiques/<the ADR file's full stem>.md`.

    DERIVED, never chosen: parent, stem and extension are all pinned. All three consumers remap
    `adrs` (measured 2026-08-02: `docs/adr`, `docs/architecture/adrs`, `docs/adr`), so a literal
    would be layout-blind — v4's B2 blocker. The checker is already GIVEN its ADR directory, so
    the ledger inherits the repo's layout for free and needs no new `layout:` area key
    (`KNOWN_KEYS["layout"]` is a closed 7-key set and would reject one).

    NOT `adr_dir.parent.parent` — that is the base `_resolves` uses, which for
    `docs/architecture/adrs` probes `docs/`. The ledger is a SIBLING of the ADR directory:
    invisible to `iter_adr_files` (which rglobs inside `adr_dir` only) and to all 12
    `DOC_BUDGETS` globs (`budget_for` → None, re-derived 2026-08-02).
    """
    return Path(adr_dir).parent / LEDGER_DIRNAME / (Path(adr_path).stem + ".md")


def laundering_signals(totals: dict) -> list[str]:
    """The statistical half of the gate — a critic that runs 6 honest checks and rubber-stamps
    them all ✅ cannot be caught mechanically (assumption A2), so it is caught in aggregate.

    Every threshold is ARITHMETIC HERE, never prose for an LLM to apply, and both
    zero-denominator cases are pinned rather than left to divide by zero:
      - `fixed == 0 and accepted > 0` FLAGS (the worst possible ratio must not pass as 0/0);
      - `Accepted == 0` SUPPRESSES the waived share (nothing to take a share of).
    """
    sig: list[str] = []
    fixed = totals.get("fixed", 0)
    accepted = totals.get("accepted_disp", 0)
    adrs_accepted = totals.get("adrs_accepted", 0)
    critiqued = totals.get("critiqued", 0)
    if accepted > 0 and (fixed == 0 or accepted / fixed > 0.5):
        sig.append("laundering:accepted-over-fixed")
    if adrs_accepted > 0 and totals.get("waived", 0) / adrs_accepted > 0.20:
        sig.append("laundering:waived-share")
    if critiqued >= 5 and totals.get("x_raised", 0) == 0 and totals.get("warn", 0) == 0:
        sig.append("laundering:all-clean")
    return sig


# The `--json` contract, pinned as VALUES so a schema cannot be "added" by writing the word
# (panel 5, 3/3 scorers: v3→v4 recorded the pinned schema as FIXED — the word landed, the schema
# did not). `test_ac16_json_schema_is_pinned_not_merely_asserted` compares emitted keys to these.
JSON_SCHEMA_ID = "adr-critique/1"
JSON_TOP_KEYS = ("schema", "adr_dir", "adrs", "totals", "signals", "vacuous")
JSON_ADR_KEYS = ("file", "status", "verdict", "ledger", "objections", "errors")
JSON_OBJECTION_KEYS = ("total", "distinct", "x_raised", "open_x", "fixed", "accepted", "warn")
JSON_TOTAL_KEYS = (
    "adrs", "adrs_accepted", "critiqued", "critique_closed", "critique_waived",
    "malformed", "misplaced", "missing", "uncritiqued", "unparsed_status",
    "x_raised", "open_x", "fixed", "accepted_disp", "warn",
)
# Any `**Key:**` marker, recognized or not. Used only to find where one header field ENDS —
# `**Status:** Accepted · **Date:** 2026-06-26` must yield Status="Accepted", not a Status that
# swallows the date. Deliberately broader than _HEADER_KEYS so an unrecognized neighbour
# (`**Related:**`) still terminates the previous value instead of polluting it.
_KEY_MARK_RE = re.compile(r"\*\*(?P<key>[A-Za-z][A-Za-z0-9 /_-]*):\*\*")
# Separator punctuation left dangling when a value is cut at the next marker (`Accepted · `).
_TRAILING_SEP = " \t·|,;•–—-"
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_PAREN_RE = re.compile(r"\([^)]*\)")
_BARE_DASH = {"", "—", "-", "–"}

# The waiver annotation and its two required parts. `waiver:` may sit inside the conventional
# trailing `(...)` or stand bare; either way the body runs to the closing paren or end of line.
_WAIVER_RE = re.compile(r"waiver:\s*(?P<body>[^)]*)", re.I)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_LETTERS_RE = re.compile(r"[A-Za-z]{3}")
WAIVER_SHAPE = "waiver: <reason> — <YYYY-MM-DD>"


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
    """Return {'Status': ..., 'Research': ...} from the template's `**Key:**` header fields
    (first occurrence wins; inline HTML comments stripped). Missing keys are absent.

    BOTH layouts are accepted, permanently and identically:

        **Status:** Accepted            |   **Status:** Accepted · **Date:** 2026-06-26
        **Date:** 2026-06-26            |

    The template emits the left one and most repos follow it, but a real consumer writes the
    right one, and the line-anchored single-match parser this replaced silently produced only
    `Status` there — with the date glued onto its value. Nothing errored: `"accepted" in
    status.lower()` still matched by substring, so the ADR was classified correctly while
    `Date` was simply absent, which made every dated waiver read as undated. A gate that cannot
    see a field it is told to read is the failure this project keeps naming, so the parser is
    fixed rather than the ratified records reformatted.

    Anti-false-positive rule preserved from the original: a line only counts as a header line
    if it BEGINS with a `**Key:**` marker, so prose that merely mentions `**Status:**` mid
    sentence is still ignored. Additional markers on such a line are then read as further
    fields, and each value stops at the next marker.
    """
    out: dict[str, str] = {}
    for raw in _COMMENT_RE.sub("", text).splitlines():
        line = raw.strip()
        marks = list(_KEY_MARK_RE.finditer(line))
        if not marks or marks[0].start() != 0:
            continue  # not a header line (prose mentioning a **Key:** never qualifies)
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
            key = m.group("key")
            if key not in _HEADER_KEYS or key in out:
                continue
            value = line[m.end():end].strip()
            if i + 1 < len(marks):  # cut mid-line: drop the separator left dangling
                value = value.rstrip(_TRAILING_SEP)
            out[key] = value
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


def split_waiver(value: str) -> tuple[str | None, str]:
    """Split a Research value into (waiver_body, value_outside_the_waiver).

    The waiver body must be excluded from path scanning: the live convention cites supporting
    material INSIDE the reason (`waiver: founder-call — 2026-06-11; spike confirmed:
    research/plugin-spike-results.md`), and a path in the reason is not the ADR's research
    trail — it is prose about why there isn't one. Scanning it would refuse every honest waiver.
    """
    m = _WAIVER_RE.search(value)
    if not m:
        return None, value
    outside = (value[: m.start()] + value[m.end() :]).strip()
    return m.group("body").strip().rstrip(";,"), outside


def check_waiver(body: str, outside: str, adr_dir: Path, adr_date: str = "") -> str | None:
    """The waiver's own gate — returns an error string, or None when the waiver stands.

    Two guardrails (ported from delivery-graph's `waiveNode`, 2026-07-11 triage):
      1. A waiver carries a REASON and is DATED. A bare `waiver:` is a one-word bypass of the
         gate that backs the harness's leading claim — it must not pass. The date may live in
         the waiver body OR in the ADR's own `**Date:**` header: the point is that the waiver is
         auditable and can age out, not that a human retypes a date the ADR already carries.
         (delivery-graph stamps `waived_at` in the engine; kbind has no engine at this layer, so
         it reads the date the template already collects rather than inventing authoring friction.)
      2. A waiver is REFUSED when the research it waives actually resolves on disk. You have
         the dossier: cite it, don't waive it. (Paths inside the reason are exempt — see
         `split_waiver`.) This is what stops the waiver becoming a silent bypass of the trace,
         and it is the load-bearing rule — guardrail 1 catches sloppiness, this one catches
         laundering.
    """
    if not body or not _LETTERS_RE.search(body):
        return f"waiver has no reason — write `{WAIVER_SHAPE}`, not a bare `waiver:`"
    if not (_DATE_RE.search(body) or _DATE_RE.search(adr_date)):
        return (
            f"waiver is undated — write `{WAIVER_SHAPE}`, or give the ADR a `**Date:**` header"
            " (an undated waiver can never age out)"
        )
    resolved = [t for t in path_tokens(outside) if _resolves(t, adr_dir)]
    if resolved:
        return (
            f"waived, but the research resolves on disk ({', '.join(repr(t) for t in resolved)})"
            " — cite it as the Research trail instead of waiving it"
        )
    return None


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

    waiver_body, outside = split_waiver(research)
    if waiver_body is not None:
        err = check_waiver(waiver_body, outside, adr_dir, header.get("Date", ""))
        if err:
            return [f"{rel}: {err}"], "traced"
        return [], "waived"  # a REASONED, DATED, evidence-free waiver — visible in the summary

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


def _zero_objections() -> dict:
    return dict.fromkeys(JSON_OBJECTION_KEYS, 0)


def check_critique(
    adr_path: Path, adr_dir: Path, header: dict[str, str]
) -> tuple[list[str], str, dict]:
    """(errors, verdict, objection-counts) for one **Accepted** ADR's objection ledger.

    LADDER PRECEDENCE, pinned: misplaced → missing → malformed → open-❌. Exactly ONE verdict per
    ADR, so colliding rows cannot double-count (a v3 finding). Each earlier rung short-circuits:
    a ledger at the wrong path is not then read and judged malformed as well.

    D64 — A BROWNFIELD REPO MUST NOT GO RED ON UPDATE. An Accepted ADR with no `**Critique:**`
    line at all is `uncritiqued`: counted, warned, exit 0. Re-measured 2026-08-02, 0 of 46 real
    ADRs across five trees carry the line, so on `harness-update` every one of them lands here
    and every consumer stays green — including the two that invoke this gate BLOCKING in CI.
    """
    counts = _zero_objections()
    rel_led = ledger_path(adr_path, adr_dir)
    value = (header.get("Critique") or "").strip()
    name = adr_path.name

    if not value:
        return [], "uncritiqued", counts

    waiver_body, outside = split_waiver(value)
    if waiver_body is not None:
        # Guardrails 1-2 come from the SHIPPED check_waiver, unmodified ("extend, don't fork").
        # Guardrail 2 provably cannot fire here — the ledger path is derived, never written on
        # the header line, so `outside` holds no path to resolve — which is exactly why 3 exists.
        err = check_waiver(waiver_body, outside, adr_dir, header.get("Date", ""))
        if err:
            return [f"{name}: **Critique:** {err}"], "critique-waiver-invalid", counts
        # GUARDRAIL 3 (new). Refuse the waiver when the ledger EXISTS (you have it — cite it),
        # or when the ADR's own **Research:** resolves. The second clause closes "waive and
        # simply never create the file", whose precondition the waiving author controls.
        research = header.get("Research", "")
        r_body, r_outside = split_waiver(research)
        research_resolves = any(
            _resolves(t, adr_dir) for t in path_tokens(r_outside if r_body is not None else research)
        )
        if rel_led.exists() or research_resolves:
            why = "the ledger exists on disk" if rel_led.exists() else "the ADR's **Research:** resolves"
            return (
                [f"{name}: **Critique:** waived, but {why} — critique it, don't waive it"],
                "critique-waiver-invalid",
                counts,
            )
        return [], "critique-waived", counts

    if value in _BARE_DASH:
        return [f"{name}: Accepted but **Critique:** is a bare dash/empty"], "critique-unfilled", counts
    if "{{" in value:
        return [f"{name}: Accepted but **Critique:** is an unfilled placeholder"], "critique-unfilled", counts

    tokens = path_tokens(value)
    if not tokens:
        return [f"{name}: **Critique:** names no ledger path"], "critique-unfilled", counts
    if not any(_same_ledger(t, rel_led, adr_dir) for t in tokens):
        return (
            [f"{name}: critique-misplaced — **Critique:** must be exactly {rel_led}, not "
             f"{', '.join(repr(t) for t in tokens)}"],
            "critique-misplaced",
            counts,
        )
    if not rel_led.exists():
        return [f"{name}: **Critique:** names {rel_led}, which does not exist"], "critique-missing", counts

    objections, fenced = parse_objections(rel_led.read_text(encoding="utf-8"))
    distinct = {o.id for o in objections}
    counts.update(
        total=len(objections),
        distinct=len(distinct),
        x_raised=sum(1 for o in objections if o.verdict == "x"),
        open_x=sum(1 for o in objections if o.verdict == "x" and o.state == "open"),
        fixed=sum(1 for o in objections if o.state == "fixed"),
        accepted=sum(1 for o in objections if o.state == "accepted"),
        warn=sum(1 for o in objections if o.verdict == "warn"),
    )
    if fenced:
        return (
            [f"{name}: critique-malformed — {rel_led} contains a fenced code block; an OBJ-N "
             f"heading inside a fence would be counted, so the ledger is rejected outright"],
            "critique-malformed",
            counts,
        )
    if len(distinct) < MIN_DISTINCT_OBJECTIONS:
        return (
            [f"{name}: critique-malformed — {rel_led} parses {len(distinct)} distinct OBJ-N "
             f"id(s), need >= {MIN_DISTINCT_OBJECTIONS} (one per adr-critic check)"],
            "critique-malformed",
            counts,
        )
    open_x = [o for o in objections if o.verdict == "x" and o.state == "open"]
    if open_x:
        ids = ", ".join(f"OBJ-{o.id}" for o in open_x)
        return (
            [f"{name}: {len(open_x)} objection(s) raised ❌ with no disposition — {ids}. Append "
             f"`— ✅ FIXED (<where>)` or `— 🔓 ACCEPTED (<reason> — <YYYY-MM-DD>)` to each."],
            "critique-open",
            counts,
        )
    return [], "critique-closed", counts


def _same_ledger(token: str, derived: Path, adr_dir: Path) -> bool:
    """Is `token` the derived ledger path? Resolved the same two ways `_resolves` resolves a
    research token, so an absolute `<adr-dir>` argument and a repo-relative header line agree."""
    target = derived.resolve()
    return any(c.resolve() == target for c in (Path(token), adr_dir.parent.parent / token))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # House style: manual argv, exit 2 on anything unrecognized. ZERO of the 30 shipped scripts
    # import argparse (measured 2026-08-02); a lone dependency style in one seeded script is drift.
    strict = "--strict" in argv
    as_json = "--json" in argv
    flags = [x for x in argv if x.startswith("--")]
    pos = [x for x in argv if not x.startswith("--")]
    if len(pos) > 1 or any(f not in ("--strict", "--json") for f in flags):
        print("usage: adr_trace_check.py [<adr-dir>] [--strict] [--json]", file=sys.stderr)
        return 2
    adr_dir = Path(pos[0] if pos else DEFAULT_ADR_DIR)
    if not adr_dir.is_dir():
        print(f"not a directory: {adr_dir}", file=sys.stderr)
        return 2

    adrs = iter_adr_files(adr_dir)
    errors: list[str] = []
    unparsed: list[str] = []
    accepted = waived = 0
    totals = dict.fromkeys(JSON_TOTAL_KEYS, 0)
    records: list[dict] = []
    uncritiqued: list[str] = []
    # Which critique verdicts are failures. `uncritiqued` and `critique-waived` are exit 0 by
    # default and errors only under --strict: the first is D64 (no brownfield goes red on
    # update), the second keeps an explicit escape hatch explicit rather than free.
    HARD = {"critique-misplaced", "critique-missing", "critique-malformed", "critique-open",
            "critique-unfilled", "critique-waiver-invalid"}
    SOFT = {"uncritiqued", "critique-waived"}

    for adr in adrs:
        errs, verdict = check_adr(adr, adr_dir)
        errors.extend(errs)
        if verdict in ("traced", "waived"):
            accepted += 1
        if verdict == "waived":
            waived += 1
        if verdict == "unparsed":
            unparsed.append(adr.name)

        header = parse_header(adr.read_text(encoding="utf-8"))
        c_errs, c_verdict, counts = ([], "not-gated", _zero_objections())
        if verdict in ("traced", "waived"):
            c_errs, c_verdict, counts = check_critique(adr, adr_dir, header)
            if c_verdict in HARD or (strict and c_verdict in SOFT):
                errors.extend(c_errs or [f"{adr.name}: {c_verdict}"])
            if c_verdict == "uncritiqued":
                uncritiqued.append(adr.name)
            totals["critique_closed"] += c_verdict == "critique-closed"
            totals["critique_waived"] += c_verdict == "critique-waived"
            totals["malformed"] += c_verdict == "critique-malformed"
            totals["misplaced"] += c_verdict == "critique-misplaced"
            totals["missing"] += c_verdict == "critique-missing"
            totals["uncritiqued"] += c_verdict == "uncritiqued"
            totals["critiqued"] += c_verdict in (
                "critique-closed", "critique-malformed", "critique-open"
            )
            for k in ("x_raised", "open_x", "fixed", "warn"):
                totals[k] += counts[k]
            totals["accepted_disp"] += counts["accepted"]
        records.append({
            "file": adr.name,
            "status": {"traced": "accepted", "waived": "accepted"}.get(verdict, verdict),
            "verdict": c_verdict,
            "ledger": str(ledger_path(adr, adr_dir)),
            "objections": counts,
            "errors": c_errs,
        })

    totals["adrs"] = len(adrs)
    totals["adrs_accepted"] = accepted
    totals["unparsed_status"] = len(unparsed)
    signals = laundering_signals({
        "fixed": totals["fixed"], "accepted_disp": totals["accepted_disp"],
        "waived": totals["critique_waived"], "adrs_accepted": accepted,
        "critiqued": totals["critiqued"], "x_raised": totals["x_raised"],
        "warn": totals["warn"],
    })
    # VACUOUS (critique): the Accepted set is non-empty and NOT ONE of it is critique-closed.
    # Kills "waive every ADR in one line each". Distinct from VACUOUS PASS (status), which means
    # the gate could not SEE the ADRs at all — different failures, separately named.
    vacuous_critique = accepted > 0 and totals["critique_closed"] == 0
    if strict and vacuous_critique:
        errors.append(
            f"{VACUOUS_CRITIQUE} — {accepted} Accepted ADR(s) and not one carries a closed "
            f"objection ledger"
        )
    # VACUOUS PASS (status): the gate could not SEE a single ADR. One predicate, used by BOTH the
    # JSON payload and the exit code — they used to be computed in different places and disagreed:
    # `vacuous.status` published `true` while the process exited 0, `--strict` included.
    #
    # The ○ branch below has always promised this escalation ("Escalation belongs behind an opt-in
    # `--strict`, not here") and never built it. The critique axis got one; the status axis did
    # not, so the emptier the gate's view, the greener it stayed — measured live in the one
    # dogfood consumer where this gate is actually wired into CI, which is the worst place for it.
    #
    # Scoped to TOTAL blindness only. Partial blindness (ERO: 9 of 12) keeps its N-of-M warning and
    # is NOT this error — a lesser state that must stay distinguishable. Default stays exit 0 (D64).
    vacuous_status = bool(adrs) and len(unparsed) == len(adrs)
    if strict and vacuous_status:
        errors.append(
            f"{VACUOUS_STATUS} — no **Status:** header parsed on any of {len(adrs)} ADR(s), so "
            f"0 were gated: the gate reports success having examined nothing"
        )

    if as_json:
        print(json.dumps({
            "schema": JSON_SCHEMA_ID,
            "adr_dir": str(adr_dir),
            "adrs": records,
            "totals": totals,
            "signals": signals,
            "vacuous": {
                "critique": vacuous_critique,
                "status": vacuous_status,
            },
        }, indent=2))
        return 1 if errors else 0

    if errors:
        print(f"✗ adr-trace check failed ({len(errors)} issue(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    summary = f"{len(adrs)} ADR(s): {accepted} accepted, {waived} waived"
    if unparsed:
        summary += f", {len(unparsed)} unparsed-status"

    # A GREEN THAT EXAMINED NOTHING REPORTS ○, NEVER ✓ (this project's own rule, applied to its
    # own gate). `accepted` is the count actually gated; when it is zero the check ran and
    # proved nothing, which a ✓ misrepresents in exactly the way a CI log gets skimmed. Measured
    # live: a consumer printed "✓ adr-trace check passed (11 ADR(s): 0 accepted, 0 waived,
    # 11 unparsed-status)" and exited 0 — green because its ADRs were invisible, not clean.
    #
    # NOT AN ERROR BY DEFAULT. Brownfield repos legitimately carry legacy un-statused ADRs and
    # D64 forbids reding a repo on update, so the default exit code is unchanged (0) and only the
    # REPORT becomes honest. The escalation this comment used to merely PROMISE is now BUILT, and
    # lives above with `vacuous_status` — `--strict` makes total blindness an error. It went
    # unbuilt for three releases while the comment claimed it, which is how the one consumer that
    # wires this gate ran it in CI, saw nothing, and was told it passed.
    # Scoped deliberately to BLINDNESS, not merely to "nothing was gated". A directory of
    # Proposed ADRs parsed perfectly and correctly found nothing to gate — that is honestly
    # ungated, not vacuous, and it keeps its ✓ (a distinction the suite already pins). The ○ is
    # for the case where the gate could not SEE: no `**Status:**` parsed anywhere, or no ADRs
    # at all.
    if not adrs:
        print("○ adr-trace examined nothing — no ADR files found")
    elif unparsed and len(unparsed) == len(adrs):
        print(
            f"○ adr-trace examined nothing — no **Status:** header parsed on any of "
            f"{len(adrs)} ADR(s), so 0 were gated ({summary})"
        )
    else:
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

    # The critique rollup goes to STDOUT, deliberately, and never first. The shipped suite pins
    # the first stdout line as the ✓/○ summary and pins `"VACUOUS" not in stderr` for a partially
    # blind run — putting this on stderr would break a green test to report a true thing.
    if totals["critiqued"] or totals["uncritiqued"] or totals["critique_waived"]:
        print(
            f"  critique: {totals['critique_closed']} closed · {totals['critique_waived']} waived"
            f" · {totals['uncritiqued']} uncritiqued · {totals['x_raised']} ❌ raised"
            f" ({totals['fixed']} fixed, {totals['accepted_disp']} accepted)"
        )
    if vacuous_critique:
        print(
            f"⚠ {VACUOUS_CRITIQUE} — {accepted} Accepted ADR(s), none with a closed objection "
            f"ledger. Run adr-critic and persist its report; --strict makes this an error."
        )
    for s in signals:
        print(f"⚠ {s}")
    if uncritiqued:
        print(
            f"⚠ adr-trace: {len(uncritiqued)} Accepted ADR(s) carry no **Critique:** line — "
            f"legacy ADRs are advisory (exit 0), new ones should be critiqued:",
            file=sys.stderr,
        )
        for name in uncritiqued[:10]:
            print(f"  - {name}", file=sys.stderr)
        if len(uncritiqued) > 10:
            print(f"  … and {len(uncritiqued) - 10} more", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

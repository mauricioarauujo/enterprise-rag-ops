#!/usr/bin/env python3
"""Deterministic agent↔KB grounding check — ADR-0015 Layer 2 (quote/span-match), the
binding-layer twin of `adr_trace_check.py`'s decision-layer trace.

Layer 1 (declared+static binding) proves an agent *names* its KB; it cannot prove an output
*grounds* in it. This check closes the deterministic half of that gap: every KB citation in
the scanned docs must (a) resolve to a real file inside the KB root and (b) quote that file
**verbatim** — a NORMALIZE'd, case-sensitive substring of the file text. Semantic paraphrase
checking is explicitly NOT this layer (Layer 3 stayed a documented option — measured
infeasible on a CPU reference machine, workshop D65).

Citation grammar (what the specialist-agent template instructs agents to emit): a markdown
blockquote whose attribution line terminates the citation —

    > The global guards enforce the tenant filter on every ORM read,
    > and the write guard rejects cross-tenant flushes before commit.
    > — kb: tenant-isolation/session-guards.md

- A blockquote line matches `^\\s{0,3}>` (CommonMark indent). EVERY attribution-matching line
  terminates a citation; its quote = the blockquote lines of the same run since the previous
  attribution line. Stacked citations in one run parse independently; trailing quote lines
  after the last attribution are plain quote text (legal).
- Marker stripping: the indent, one `>`, at most one following space; a nested `>>` keeps its
  remaining `>` as text; a bare `>` line is whitespace.
- Fences: a delimiter is a RAW line matching `^```' (a quoted `> ```` is text and does not
  toggle; tilde/indented fences do not toggle). State is global per file; unclosed → EOF.
  Fenced lines are excluded (docs legitimately show example citations in fences).
- Malformed-attribution sentinel: an attribution-SHAPED line (`^\\s{0,3}>\\s*[—–-]\\s*kb\\s*:`)
  that fails the full regex is a finding — a typo'd attribution fails loudly instead of
  silently degrading to plain quote. `kb:` anywhere else in quoted text is never flagged.

Finding classes: unresolved-path · escaping-path · quote-mismatch · short-quote ·
malformed-attribution. Per citation the checks run path → length → substring; the first
failure emits ONE finding. Reported line = the attribution line (1-based).

NORMALIZE (identical on quote and KB text): unicode NFC → typographic map (curly quotes,
en/em dash, ellipsis, NBSP) → strip `**` and backticks (`_` kept: snake_case) → collapse
whitespace → case-SENSITIVE match. MIN_QUOTE_CHARS = 20 normalized chars.

Vacuous-pass honesty (mirrors adr_trace_check): zero citations found → exit 0 with a stderr
warning naming the vacuous run — bound agents may not be citing yet; a green that checked
nothing must read as vacuous, not healthy. Absence of citations is advisory by design
(demanding them everywhere would be a waiver-burst generator on brownfield repos).

Usage:
    python3 kb_cite_check.py <kb-root> [<scan-root>...]   # default scan root: docs
Exit: 0 clean (incl. vacuous) · 1 findings · 2 bad usage (missing/non-dir kb-root, or an
EXPLICITLY passed scan-root that is missing/non-dir; the absent DEFAULT `docs` is vacuous-
eligible — a default must not fail a repo that has no docs/ yet).
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SCAN_ROOT = "docs"
MIN_QUOTE_CHARS = 20
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "_archive"}
CLASSES = ("unresolved-path", "escaping-path", "quote-mismatch", "short-quote",
           "malformed-attribution")

_BQ_RE = re.compile(r"^\s{0,3}>")
_ATTR_RE = re.compile(r"^\s{0,3}>\s*[—–-]\s*kb:\s*(?P<path>\S+)\s*$")
_ATTR_SHAPE_RE = re.compile(r"^\s{0,3}>\s*[—–-]\s*kb\s*:")
_MARKER_RE = re.compile(r"^\s{0,3}> ?")

_TYPO_MAP = {"“": '"', "”": '"', "‘": "'", "’": "'",
             "–": "-", "—": "-", "…": "...", " ": " "}
_STRIP_TOKENS = ("**", "`")


def normalize(text: str) -> str:
    """The pinned NORMALIZE — applied identically to quotes and KB file text."""
    text = unicodedata.normalize("NFC", text)
    for src, dst in _TYPO_MAP.items():
        text = text.replace(src, dst)
    for tok in _STRIP_TOKENS:
        text = text.replace(tok, "")
    return " ".join(text.split())


@dataclass
class Citation:
    file: Path
    line: int  # the attribution line, 1-based
    path: str  # as written, relative to the KB root
    quote: str  # marker-stripped quote lines joined by single spaces


@dataclass
class Finding:
    file: Path
    line: int
    cls: str
    msg: str


def extract(file: Path) -> tuple[list[Citation], list[Finding]]:
    """Extract citations + malformed-attribution findings from one markdown file."""
    citations: list[Citation] = []
    malformed: list[Finding] = []
    in_fence = False
    quote_buf: list[str] = []
    prev_was_bq = False
    for lineno, line in enumerate(file.read_text(encoding="utf-8", errors="replace")
                                  .splitlines(), start=1):
        if line.startswith("```"):  # raw-line fence delimiter only (a quoted one is text)
            in_fence = not in_fence
            prev_was_bq, quote_buf = False, []
            continue
        if in_fence:
            prev_was_bq = False
            continue
        if _BQ_RE.match(line):
            if not prev_was_bq:
                quote_buf = []  # a new blockquote run
            m = _ATTR_RE.match(line)
            if m:
                citations.append(Citation(file, lineno, m["path"],
                                          " ".join(quote_buf)))
                quote_buf = []
            elif _ATTR_SHAPE_RE.match(line):
                malformed.append(Finding(
                    file, lineno, "malformed-attribution",
                    f"attribution-shaped line does not parse: {line.strip()[:80]}"))
            else:
                quote_buf.append(_MARKER_RE.sub("", line, count=1))
            prev_was_bq = True
        else:
            prev_was_bq, quote_buf = False, []
    return citations, malformed


def check_citation(cite: Citation, kb_root: Path) -> Finding | None:
    """Pinned precedence: path resolution → length → substring. One finding max."""
    target = (kb_root / cite.path)
    try:
        resolved = target.resolve()
    except OSError:
        resolved = None
    if resolved is None or not resolved.is_relative_to(kb_root.resolve()):
        return Finding(cite.file, cite.line, "escaping-path",
                       f"path escapes the KB root: {cite.path}")
    if not resolved.is_file():
        return Finding(cite.file, cite.line, "unresolved-path",
                       f"no such KB file: {cite.path}")
    quote = normalize(cite.quote)
    if len(quote) < MIN_QUOTE_CHARS:
        return Finding(cite.file, cite.line, "short-quote",
                       "quote too short to verify — extend the quote")
    text = normalize(resolved.read_text(encoding="utf-8", errors="replace"))
    if quote not in text:
        return Finding(cite.file, cite.line, "quote-mismatch",
                       f"quote not found in {cite.path}: \"{quote[:60]}\"")
    return None


def iter_md_files(scan_roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in scan_roots:
        files.extend(p for p in sorted(root.rglob("*.md"))
                     if not (set(p.parts) & SKIP_DIRS))
    return files


def check_tree(kb_root: Path, scan_roots: list[Path]) -> tuple[list[Finding], int]:
    """Return (findings, citations_checked) over every .md under the scan roots."""
    findings: list[Finding] = []
    n_citations = 0
    for f in iter_md_files([r for r in scan_roots if r.is_dir()]):
        citations, malformed = extract(f)
        findings.extend(malformed)
        n_citations += len(citations)
        for cite in citations:
            finding = check_citation(cite, kb_root)
            if finding:
                findings.append(finding)
    return findings, n_citations


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: kb_cite_check.py <kb-root> [<scan-root>...]", file=sys.stderr)
        return 2
    kb_root = Path(argv[0])
    if not kb_root.is_dir():
        print(f"not a directory: {kb_root}", file=sys.stderr)
        return 2
    explicit = [Path(a) for a in argv[1:]]
    for root in explicit:  # an EXPLICIT scan-root must exist; the default may be absent
        if not root.is_dir():
            print(f"not a directory: {root}", file=sys.stderr)
            return 2
    scan_roots = explicit or [Path(DEFAULT_SCAN_ROOT)]

    files = iter_md_files([r for r in scan_roots if r.is_dir()])
    findings, n_citations = check_tree(kb_root, scan_roots)

    if findings:
        print(f"✗ kb-cite check: {len(findings)} finding(s):")
        for f in findings:
            print(f"  - {f.file}:{f.line} — [{f.cls}] {f.msg}")
        by_cls = {c: sum(1 for f in findings if f.cls == c) for c in CLASSES}
        summary = " · ".join(f"{c} {n}" for c, n in by_cls.items() if n)
        print(f"  {len(files)} file(s) scanned, {n_citations} citation(s) checked — {summary}")
        return 1

    print(f"✓ kb-cite check passed ({len(files)} file(s) scanned, "
          f"{n_citations} citation(s) checked)")
    if n_citations == 0:
        print("warning: Layer 2 ran vacuously — no KB citations found; bound agents may "
              "not be citing yet (see the specialist template's Grounding citations section)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

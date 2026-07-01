#!/usr/bin/env python3
"""Shared deterministic helpers for the machine-validity anchors (Sprint A1 / P-1).

Pure stdlib, no LLM, no network. Three jobs, each a pure function so each script + test
reads the same truth:
  - parse_junit(path)        -> {test_name: "pass"|"fail"|"error"|"skip"}
  - assert_counts(tests_dir) -> {test_name: non_trivial_assert_count}   (Python AST)
  - test_acs(tests_dir)      -> {test_name: set("AC-N", ...)}            (name + docstring tags)

Polyglot (fail-closed, ADR-0013 R3 spirit): assert counting is Python-`ast` only. For a test
file the AST can't parse (another language, or a syntax error), the test simply contributes no
assert-count — callers MUST treat a missing/zero count as `unproven`, never as proof. So a
non-Python suite degrades to `unproven`, it never false-`proven`s.
"""
from __future__ import annotations

import ast
import fnmatch
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# AC ids are phase-scoped (each DEFINE numbers AC-1, AC-2, … from zero). To let phases share one
# `tests/` tree without colliding, an id may carry an optional phase QUALIFIER and/or a letter
# SUFFIX. All three anchors (ac_test_check, ac_green_check, red_baseline/diff_gate) import THIS
# regex so they agree on exactly what an AC id is.
#   AC-3        plain (namespace "")            — single-phase / legacy, unchanged
#   AC-4b       letter suffix (a sub-criterion) — now a first-class id (was invisible before)
#   AC-S04P1-3  phase-qualified (namespace "S04P1") — collision-proof across phases in one tree
#   AC-S04P1-3b qualified + suffix
AC_RE = re.compile(r"\bAC-(?:[A-Za-z0-9]+-)?\d+[a-z]?\b")
_ASSERT_METHOD_RE = re.compile(r"^assert[_A-Z]")  # unittest: assertEqual, assertTrue, assert_called...
_ASSERT_CALL_NAMES = {"expect", "raises", "assert_called", "assert_called_once", "assert_called_with"}

# test-file shapes — the single SSoT of "what is a test file"; ac_test_check imports it so the
# two anchors can never disagree.
TEST_GLOBS = (
    "test_*.py", "*_test.py",
    "*.test.ts", "*.test.js", "*.test.tsx", "*.spec.ts", "*.spec.js",
    "*_test.go", "*Test.java", "*_spec.rb", "*_test.rs",
)


def ids_in(text: str) -> set[str]:
    """Every AC id (plain / suffixed / phase-qualified) referenced in a blob of text."""
    return set(AC_RE.findall(text))


def ac_namespace(ac: str) -> str:
    """The phase namespace of an AC id: the qualifier for `AC-<QUAL>-<n>`, else "" for plain
    `AC-<n>`. Two ids collide only when they share a namespace AND the same number+suffix."""
    body = ac[3:]  # strip "AC-"
    return body.rsplit("-", 1)[0] if "-" in body else ""


def ac_sort_key(ac: str) -> tuple[str, int, str]:
    """Stable order for ids of any shape: (namespace, number, letter-suffix)."""
    body = ac[3:]
    ns, num = body.rsplit("-", 1) if "-" in body else ("", body)
    m = re.match(r"(\d+)([a-z]*)$", num)
    return (ns, int(m.group(1)) if m else 0, m.group(2) if m else "")


def own_namespace(ids) -> str:
    """The single namespace a phase's own criteria live in — the dominant namespace among its
    declared ids (ties prefer the plain "" namespace). A DEFINE declares criteria in one
    namespace; a stray cross-phase reference in prose (e.g. `…asserted upstream by AC-P3-06`)
    lands in a different namespace and is NOT this phase's criterion, so the checks exclude it."""
    if not ids:
        return ""
    counts = Counter(ac_namespace(a) for a in ids)
    top = max(counts.values())
    tied = {ns for ns, c in counts.items() if c == top}
    return "" if "" in tied else sorted(tied)[0]


def parse_junit(path: str | Path) -> dict[str, str]:
    """Map each junit <testcase> to a status. Malformed/partial XML -> {} (caller fail-closes)."""
    try:
        root = ET.parse(str(path)).getroot()
    except (ET.ParseError, OSError):
        return {}
    out: dict[str, str] = {}
    for tc in root.iter("testcase"):
        name = tc.get("name") or ""
        if not name:
            continue
        status = "pass"
        for child in tc:
            tag = child.tag.lower()
            if tag == "failure":
                status = "fail"
            elif tag == "error":
                status = "error"
            elif tag == "skipped":
                status = "skip"
        # if a name appears twice (parametrized / collision), a single fail taints it
        if name in out and out[name] == "pass":
            out[name] = status if status != "pass" else out[name]
        else:
            out[name] = status
    return out


def _is_trivial(node: ast.Assert) -> bool:
    """`assert True` / `assert 1` / `assert x == x` — asserts that prove nothing."""
    test = node.test
    if isinstance(test, ast.Constant):
        return True
    if isinstance(test, ast.Compare) and len(test.comparators) == 1:
        try:
            return ast.dump(test.left) == ast.dump(test.comparators[0])
        except Exception:
            return False
    return False


def _count_nontrivial(func: ast.AST) -> int:
    n = 0
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            if not _is_trivial(node):
                n += 1
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
            if name and (_ASSERT_METHOD_RE.match(name) or name in _ASSERT_CALL_NAMES):
                n += 1
        elif isinstance(node, ast.With):  # `with pytest.raises(...)` / `with self.assertRaises(...)`
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call):
                    fn = call.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
                    if name and ("raises" in name.lower() or _ASSERT_METHOD_RE.match(name or "")):
                        n += 1
    return n


def iter_test_files(tests_dir: str | Path, include: list[str] | None = None) -> list[Path]:
    """Test files under `tests_dir`. With `include` globs, keep only files whose name OR
    root-relative posix path matches at least one glob — the per-phase scope (direction A):
    scan just this phase's tests so foreign phases in a shared tree don't leak in."""
    root = Path(tests_dir)
    files: list[Path] = []
    for glob in TEST_GLOBS:
        files.extend(root.rglob(glob))
    files = sorted(set(files))
    if include:
        kept: list[Path] = []
        for f in files:
            rel = f.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(f.name, p) for p in include):
                kept.append(f)
        files = kept
    return files


# Back-compat alias (was private before helpers were centralised here).
_iter_test_files = iter_test_files


def _walk_py_tests(tests_dir: str | Path, include: list[str] | None = None):
    """Yield (test_name, func_node, docstring) for python test functions/methods."""
    for f in iter_test_files(tests_dir, include):
        if f.suffix != ".py":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        def visit(body):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    yield node.name, node, (ast.get_docstring(node) or "")
                elif isinstance(node, ast.ClassDef):
                    yield from visit(node.body)

        yield from visit(tree.body)


def assert_counts(tests_dir: str | Path, include: list[str] | None = None) -> dict[str, int]:
    """{test_name: non_trivial_assert_count} across Python test files (last write wins on collision)."""
    out: dict[str, int] = {}
    for name, node, _ in _walk_py_tests(tests_dir, include):
        out[name] = _count_nontrivial(node)
    return out


def test_acs(tests_dir: str | Path, include: list[str] | None = None) -> dict[str, set[str]]:
    """{test_name: {AC ids it covers}} from the AC-N tags in the test name + docstring."""
    out: dict[str, set[str]] = {}
    for name, _, doc in _walk_py_tests(tests_dir, include):
        out[name] = ids_in(name) | ids_in(doc)
    return out


def declared_acs(define_text: str) -> set[str]:
    return ids_in(define_text)

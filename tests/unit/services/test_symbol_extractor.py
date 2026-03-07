"""Brutal tests for the symbol extractor service (AVOS-020).

Covers: Python AST extraction, regex fallback for unknown languages,
canonical normalization format, deterministic ordering, graceful
degradation on malformed/binary/missing files, and path safety.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avos_cli.services.symbol_extractor import extract_symbols


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Minimal repo root with .git marker."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def _write(repo: Path, rel: str, content: str) -> Path:
    """Write a file relative to repo root and return its absolute path."""
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Python AST extraction
# ---------------------------------------------------------------------------

class TestPythonAST:
    """Symbol extraction using Python's ast module."""

    def test_functions_and_classes(self, repo: Path) -> None:
        src = _write(repo, "pkg/module.py", (
            "def top_func():\n"
            "    pass\n\n"
            "class MyClass:\n"
            "    def method_a(self):\n"
            "        pass\n\n"
            "    def method_b(self):\n"
            "        pass\n\n"
            "async def async_func():\n"
            "    pass\n"
        ))
        symbols = extract_symbols(src, repo)
        assert len(symbols) >= 4
        # Canonical format: python:<namespace>::<name>#<kind>
        assert any("top_func#function" in s for s in symbols)
        assert any("MyClass#class" in s for s in symbols)
        assert any("method_a#method" in s for s in symbols)
        assert any("async_func#function" in s for s in symbols)
        # All must start with "python:"
        for s in symbols:
            assert s.startswith("python:"), f"Expected python: prefix, got {s}"

    def test_nested_class(self, repo: Path) -> None:
        src = _write(repo, "nested.py", (
            "class Outer:\n"
            "    class Inner:\n"
            "        def deep(self):\n"
            "            pass\n"
        ))
        symbols = extract_symbols(src, repo)
        assert any("Outer#class" in s for s in symbols)
        assert any("Inner#class" in s for s in symbols)
        assert any("deep#method" in s for s in symbols)

    def test_empty_python_file(self, repo: Path) -> None:
        src = _write(repo, "empty.py", "")
        symbols = extract_symbols(src, repo)
        assert symbols == []

    def test_python_with_only_imports(self, repo: Path) -> None:
        src = _write(repo, "imports_only.py", "import os\nfrom sys import argv\n")
        symbols = extract_symbols(src, repo)
        assert symbols == []

    def test_syntax_error_python_falls_back(self, repo: Path) -> None:
        """Malformed Python should not raise; may fall back to regex."""
        src = _write(repo, "bad.py", "def broken(\n")
        symbols = extract_symbols(src, repo)
        # Should not raise; may return empty or regex-extracted partial
        assert isinstance(symbols, list)


# ---------------------------------------------------------------------------
# Regex fallback for non-Python languages
# ---------------------------------------------------------------------------

class TestRegexFallback:
    """Regex-based extraction for JS/TS/Go and unknown languages."""

    def test_javascript_functions(self, repo: Path) -> None:
        src = _write(repo, "app.js", (
            "function fetchData() {}\n"
            "class ApiClient {\n"
            "  constructor() {}\n"
            "}\n"
        ))
        symbols = extract_symbols(src, repo)
        assert any("fetchData" in s for s in symbols)
        assert any("ApiClient" in s for s in symbols)

    def test_typescript_file(self, repo: Path) -> None:
        src = _write(repo, "service.ts", (
            "export function handleRequest() {}\n"
            "export class Router {}\n"
        ))
        symbols = extract_symbols(src, repo)
        assert any("handleRequest" in s for s in symbols)
        assert any("Router" in s for s in symbols)

    def test_go_functions(self, repo: Path) -> None:
        src = _write(repo, "main.go", (
            "func main() {}\n"
            "func (s *Server) Start() {}\n"
        ))
        symbols = extract_symbols(src, repo)
        assert any("main" in s for s in symbols)
        assert any("Start" in s for s in symbols)

    def test_unknown_extension(self, repo: Path) -> None:
        src = _write(repo, "script.rb", "def hello\nend\nclass Greeter\nend\n")
        symbols = extract_symbols(src, repo)
        # Regex should still pick up def/class patterns
        assert any("hello" in s for s in symbols)
        assert any("Greeter" in s for s in symbols)
        for s in symbols:
            assert s.startswith("unknown:") or s.startswith("ruby:")


# ---------------------------------------------------------------------------
# Canonical normalization format
# ---------------------------------------------------------------------------

class TestNormalization:
    """Verify canonical key format: <language>:<namespace>::<name>#<kind>."""

    def test_format_structure(self, repo: Path) -> None:
        src = _write(repo, "pkg/sub/mod.py", "def helper(): pass\n")
        symbols = extract_symbols(src, repo)
        assert len(symbols) == 1
        s = symbols[0]
        parts = s.split(":")
        assert len(parts) >= 2, f"Expected at least lang:rest, got {s}"
        assert parts[0] == "python"
        assert "#" in s, f"Expected #kind suffix, got {s}"

    def test_namespace_uses_dots(self, repo: Path) -> None:
        src = _write(repo, "a/b/c.py", "class Foo: pass\n")
        symbols = extract_symbols(src, repo)
        assert len(symbols) == 1
        # namespace_path should use dot-separated path
        assert "a.b.c" in symbols[0] or "a/b/c" not in symbols[0]


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Output must be sorted identically across runs."""

    def test_stable_order_across_runs(self, repo: Path) -> None:
        src = _write(repo, "multi.py", (
            "def z_func(): pass\n"
            "def a_func(): pass\n"
            "class M_Class: pass\n"
            "def b_func(): pass\n"
        ))
        results = [extract_symbols(src, repo) for _ in range(3)]
        assert results[0] == results[1] == results[2]
        assert len(results[0]) == 4


# ---------------------------------------------------------------------------
# Graceful degradation / hostile cases
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Extraction never raises; returns empty list on failure."""

    def test_nonexistent_file(self, repo: Path) -> None:
        missing = repo / "does_not_exist.py"
        symbols = extract_symbols(missing, repo)
        assert symbols == []

    def test_binary_file(self, repo: Path) -> None:
        binfile = repo / "image.png"
        binfile.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        symbols = extract_symbols(binfile, repo)
        assert symbols == []

    def test_path_outside_repo(self, repo: Path) -> None:
        """File outside repo root should return empty (path safety)."""
        outside = repo.parent / "outside.py"
        outside.write_text("def secret(): pass\n")
        symbols = extract_symbols(outside, repo)
        assert symbols == []

    def test_directory_instead_of_file(self, repo: Path) -> None:
        d = repo / "some_dir"
        d.mkdir()
        symbols = extract_symbols(d, repo)
        assert symbols == []

    def test_permission_denied(self, repo: Path) -> None:
        """Unreadable file should degrade gracefully."""
        src = _write(repo, "locked.py", "def secret(): pass\n")
        src.chmod(0o000)
        try:
            symbols = extract_symbols(src, repo)
            assert symbols == []
        finally:
            src.chmod(0o644)

    def test_very_large_file(self, repo: Path) -> None:
        """Large file should still return without hanging."""
        lines = ["def func_%d(): pass\n" % i for i in range(500)]
        src = _write(repo, "big.py", "".join(lines))
        symbols = extract_symbols(src, repo)
        assert len(symbols) == 500

    def test_diff_context_parameter_accepted(self, repo: Path) -> None:
        """diff_context is accepted but optional; should not break."""
        src = _write(repo, "ctx.py", "def target(): pass\n")
        symbols = extract_symbols(src, repo, diff_context="@@ -1,3 +1,5 @@")
        assert len(symbols) >= 1

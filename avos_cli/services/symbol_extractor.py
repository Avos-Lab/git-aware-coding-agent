"""Symbol extraction service for enriching WIP artifacts (AVOS-020).

Extracts function, class, and method definitions from source files and
returns them in canonical normalized format. Uses Python AST for .py files
and regex heuristics as fallback for other languages.

Canonical key format: <language>:<namespace_path>::<symbol_name>#<kind>

Public API:
    extract_symbols -- main entry point, never raises on extraction failure
"""

from __future__ import annotations

import ast
import re
import unicodedata
from pathlib import Path

from avos_cli.utils.logger import get_logger

_log = get_logger("services.symbol_extractor")

_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
}

_REGEX_FUNCTION = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|func)\s+(\w+)",
    re.MULTILINE,
)
_REGEX_CLASS = re.compile(
    r"^\s*(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_REGEX_METHOD = re.compile(
    r"^\s+(?:async\s+)?def\s+(\w+)",
    re.MULTILINE,
)
_REGEX_GO_METHOD = re.compile(
    r"^\s*func\s+\([^)]+\)\s+(\w+)",
    re.MULTILINE,
)


def extract_symbols(
    file_path: Path,
    repo_root: Path,
    diff_context: str | None = None,
) -> list[str]:
    """Extract normalized symbol keys from a source file.

    Returns a sorted list of canonical symbol strings. Never raises on
    extraction failure -- returns an empty list instead.

    Args:
        file_path: Absolute path to the source file.
        repo_root: Repository root for namespace derivation.
        diff_context: Optional diff hunk context (reserved for future use).

    Returns:
        Sorted list of canonical symbol keys.
    """
    try:
        return _extract_safe(file_path, repo_root, diff_context)
    except Exception as exc:
        _log.debug("Symbol extraction failed for %s: %s", file_path, exc)
        return []


def _extract_safe(
    file_path: Path,
    repo_root: Path,
    diff_context: str | None,
) -> list[str]:
    """Inner extraction with validation guards."""
    if not file_path.is_file():
        return []

    resolved = file_path.resolve()
    repo_resolved = repo_root.resolve()
    try:
        resolved.relative_to(repo_resolved)
    except ValueError:
        _log.debug("Path %s is outside repo root %s", file_path, repo_root)
        return []

    try:
        content = file_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return []

    suffix = file_path.suffix.lower()
    language = _LANGUAGE_MAP.get(suffix, "unknown")
    namespace = _derive_namespace(file_path, repo_root)

    if language == "python":
        symbols = _extract_python_ast(content, namespace)
        if symbols is not None:
            return sorted(symbols)

    raw = _extract_regex(content, language, namespace)
    return sorted(raw)


def _derive_namespace(file_path: Path, repo_root: Path) -> str:
    """Derive dot-separated namespace from file path relative to repo root.

    Args:
        file_path: Absolute path to the source file.
        repo_root: Repository root directory.

    Returns:
        Dot-separated namespace string (e.g. 'pkg.sub.module').
    """
    try:
        rel = file_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return ""
    parts = list(rel.parts)
    if parts and "." in parts[-1]:
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    return ".".join(parts)


def _normalize_name(name: str) -> str:
    """Normalize a symbol name: NFKC unicode, strip whitespace."""
    return unicodedata.normalize("NFKC", name).strip()


def _make_key(language: str, namespace: str, name: str, kind: str) -> str:
    """Build canonical symbol key."""
    norm = _normalize_name(name)
    return f"{language}:{namespace}::{norm}#{kind}"


def _extract_python_ast(
    content: str,
    namespace: str,
) -> list[str] | None:
    """Extract symbols from Python source using the ast module.

    Returns None if parsing fails (caller should fall back to regex).

    Args:
        content: Python source code string.
        namespace: Dot-separated namespace prefix.

    Returns:
        List of canonical symbol keys, or None on parse failure.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    symbols: list[str] = []
    _walk_python_ast(tree, namespace, symbols, parent_is_class=False)
    return symbols


def _walk_python_ast(
    node: ast.AST,
    namespace: str,
    symbols: list[str],
    *,
    parent_is_class: bool,
) -> None:
    """Recursively walk AST nodes collecting function/class definitions."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if parent_is_class else "function"
            symbols.append(_make_key("python", namespace, child.name, kind))
            _walk_python_ast(child, namespace, symbols, parent_is_class=False)
        elif isinstance(child, ast.ClassDef):
            symbols.append(_make_key("python", namespace, child.name, "class"))
            _walk_python_ast(child, namespace, symbols, parent_is_class=True)


def _extract_regex(
    content: str,
    language: str,
    namespace: str,
) -> list[str]:
    """Extract symbols using regex heuristics for any language.

    Args:
        content: Source file content.
        language: Detected language string.
        namespace: Dot-separated namespace prefix.

    Returns:
        List of canonical symbol keys.
    """
    symbols: list[str] = []
    seen: set[str] = set()

    for match in _REGEX_CLASS.finditer(content):
        name = match.group(1)
        key = _make_key(language, namespace, name, "class")
        if key not in seen:
            seen.add(key)
            symbols.append(key)

    for match in _REGEX_FUNCTION.finditer(content):
        name = match.group(1)
        key = _make_key(language, namespace, name, "function")
        if key not in seen:
            seen.add(key)
            symbols.append(key)

    if language == "go":
        for match in _REGEX_GO_METHOD.finditer(content):
            name = match.group(1)
            key = _make_key(language, namespace, name, "method")
            if key not in seen:
                seen.add(key)
                symbols.append(key)

    return symbols

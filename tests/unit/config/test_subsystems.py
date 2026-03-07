"""Brutal tests for the subsystem mapping loader (AVOS-021).

Covers: valid YAML loading, missing file, malformed YAML, glob matching,
empty mapping, non-dict structures, and deterministic resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avos_cli.config.subsystems import load_subsystem_mapping, resolve_subsystems


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def avos_dir(tmp_path: Path) -> Path:
    """Create a .avos directory."""
    d = tmp_path / ".avos"
    d.mkdir()
    return d


def _write_subsystems(avos_dir: Path, content: str) -> Path:
    """Write subsystems.yml and return its path."""
    p = avos_dir / "subsystems.yml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_subsystem_mapping
# ---------------------------------------------------------------------------

class TestLoadSubsystemMapping:
    """Tests for loading .avos/subsystems.yml."""

    def test_valid_mapping(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, (
            "frontend:\n"
            "  - 'src/components/**'\n"
            "  - 'src/pages/**'\n"
            "backend:\n"
            "  - 'api/**'\n"
            "  - 'services/**'\n"
        ))
        mapping = load_subsystem_mapping(avos_dir)
        assert "frontend" in mapping
        assert "backend" in mapping
        assert "src/components/**" in mapping["frontend"]
        assert len(mapping["backend"]) == 2

    def test_missing_file_returns_empty(self, avos_dir: Path) -> None:
        mapping = load_subsystem_mapping(avos_dir)
        assert mapping == {}

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        mapping = load_subsystem_mapping(tmp_path / "nonexistent")
        assert mapping == {}

    def test_empty_file_returns_empty(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, "")
        mapping = load_subsystem_mapping(avos_dir)
        assert mapping == {}

    def test_malformed_yaml_returns_empty(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, "{{{{invalid yaml: [")
        mapping = load_subsystem_mapping(avos_dir)
        assert mapping == {}

    def test_non_dict_top_level_returns_empty(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, "- item1\n- item2\n")
        mapping = load_subsystem_mapping(avos_dir)
        assert mapping == {}

    def test_non_list_values_skipped(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, (
            "valid:\n"
            "  - 'src/**'\n"
            "invalid: 'not_a_list'\n"
            "also_invalid: 42\n"
        ))
        mapping = load_subsystem_mapping(avos_dir)
        assert "valid" in mapping
        assert "invalid" not in mapping
        assert "also_invalid" not in mapping

    def test_non_string_patterns_filtered(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, (
            "mixed:\n"
            "  - 'src/**'\n"
            "  - 42\n"
            "  - null\n"
        ))
        mapping = load_subsystem_mapping(avos_dir)
        assert mapping["mixed"] == ["src/**"]

    def test_single_subsystem(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, "infra:\n  - 'deploy/**'\n")
        mapping = load_subsystem_mapping(avos_dir)
        assert mapping == {"infra": ["deploy/**"]}

    def test_unicode_subsystem_names(self, avos_dir: Path) -> None:
        _write_subsystems(avos_dir, "données:\n  - 'data/**'\n")
        mapping = load_subsystem_mapping(avos_dir)
        assert "données" in mapping


# ---------------------------------------------------------------------------
# resolve_subsystems
# ---------------------------------------------------------------------------

class TestResolveSubsystems:
    """Tests for resolving file paths to subsystem names."""

    def test_single_match(self) -> None:
        mapping = {"frontend": ["src/components/*"]}
        result = resolve_subsystems("src/components/Button.tsx", mapping)
        assert result == ["frontend"]

    def test_multiple_matches(self) -> None:
        mapping = {
            "frontend": ["src/**"],
            "shared": ["src/shared/**"],
        }
        result = resolve_subsystems("src/shared/utils.ts", mapping)
        assert "frontend" in result
        assert "shared" in result

    def test_no_match(self) -> None:
        mapping = {"frontend": ["src/components/*"]}
        result = resolve_subsystems("api/routes.py", mapping)
        assert result == []

    def test_empty_mapping(self) -> None:
        result = resolve_subsystems("any/file.py", {})
        assert result == []

    def test_glob_double_star(self) -> None:
        mapping = {"backend": ["api/**"]}
        result = resolve_subsystems("api/v2/routes/users.py", mapping)
        assert result == ["backend"]

    def test_glob_single_star(self) -> None:
        mapping = {"tests": ["tests/*"]}
        result = resolve_subsystems("tests/test_foo.py", mapping)
        assert result == ["tests"]

    def test_deterministic_ordering(self) -> None:
        mapping = {
            "z_system": ["src/**"],
            "a_system": ["src/**"],
            "m_system": ["src/**"],
        }
        results = [resolve_subsystems("src/file.py", mapping) for _ in range(3)]
        assert results[0] == results[1] == results[2]
        assert results[0] == sorted(results[0])

    def test_empty_file_path(self) -> None:
        mapping = {"frontend": ["src/**"]}
        result = resolve_subsystems("", mapping)
        assert result == []

    def test_path_with_special_chars(self) -> None:
        mapping = {"docs": ["docs/**"]}
        result = resolve_subsystems("docs/[guide].md", mapping)
        # fnmatch may or may not match brackets; should not crash
        assert isinstance(result, list)

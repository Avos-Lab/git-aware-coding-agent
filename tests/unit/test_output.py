"""Tests for output formatting helpers.

Validates JSON envelope, verbose suppression, progress bar suppression,
and Rich rendering helpers (table, panel, tree, kv_panel).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from avos_cli.utils.output import (
    create_progress,
    print_json,
    print_verbose,
    render_kv_panel,
    render_panel,
    render_table,
    render_tree,
)


class TestPrintJson:
    """Validate print_json emits strict envelope."""

    def test_success_envelope_has_required_keys(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_json(success=True, data={"note_id": "abc"}, error=None)
        captured = capsys.readouterr()
        out = captured.out + captured.err
        obj = json.loads(out.strip())
        assert "success" in obj
        assert "data" in obj
        assert "error" in obj
        assert obj["success"] is True
        assert obj["data"] == {"note_id": "abc"}
        assert obj["error"] is None

    def test_error_envelope_has_required_keys(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_json(
            success=False,
            data=None,
            error={"code": "AUTH_ERROR", "message": "Bad key", "hint": "Check env", "retryable": False},
        )
        captured = capsys.readouterr()
        out = captured.out + captured.err
        obj = json.loads(out.strip())
        assert obj["success"] is False
        assert obj["data"] is None
        assert obj["error"]["code"] == "AUTH_ERROR"

    def test_output_is_valid_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_json(success=True, data={"x": 1, "y": [2, 3]}, error=None)
        captured = capsys.readouterr()
        out = captured.out + captured.err
        parsed = json.loads(out.strip())
        assert parsed["data"]["x"] == 1
        assert parsed["data"]["y"] == [2, 3]


class TestPrintVerbose:
    """Validate print_verbose respects verbose flag."""

    def test_prints_when_verbose_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_verbose("DEBUG", "some message", verbose=True)
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "DEBUG" in out or "some message" in out

    def test_suppresses_when_verbose_false(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_verbose("DEBUG", "hidden message", verbose=False)
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "hidden message" not in out


class TestCreateProgressSuppress:
    """Validate create_progress can be suppressed for JSON mode."""

    def test_suppress_returns_context_manager(self) -> None:
        progress = create_progress("Test", suppress=True)
        with progress:
            pass

    def test_suppress_does_not_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        progress = create_progress("Processing", suppress=True)
        with progress:
            pass
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "Processing" not in out or len(out.strip()) == 0


class TestGoldenOutput:
    """Validate output against golden snapshots."""

    def test_json_success_matches_golden(self, capsys: pytest.CaptureFixture[str]) -> None:
        golden_path = Path(__file__).resolve().parents[1] / "golden" / "json_envelope_success.golden"
        if not golden_path.exists():
            pytest.skip(f"Golden file not found: {golden_path}")
        expected = json.loads(golden_path.read_text().strip())
        print_json(success=True, data=expected["data"], error=None)
        captured = capsys.readouterr()
        actual = json.loads((captured.out + captured.err).strip())
        assert actual == expected


class TestRenderTablePlainText:
    """Validate render_table in non-TTY (plain text) mode."""

    @patch("avos_cli.utils.output.is_interactive", return_value=False)
    def test_renders_title_and_rows(self, _mock: object, capsys: pytest.CaptureFixture[str]) -> None:
        render_table(
            "My Table",
            [("Name", ""), ("Value", "")],
            [["alice", "100"], ["bob", "200"]],
        )
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "My Table" in out
        assert "alice" in out
        assert "bob" in out
        assert "100" in out

    @patch("avos_cli.utils.output.is_interactive", return_value=False)
    def test_empty_rows(self, _mock: object, capsys: pytest.CaptureFixture[str]) -> None:
        render_table("Empty", [("Col", "")], [])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "Empty" in out
        assert "Col" in out


class TestRenderTableRich:
    """Validate render_table in TTY (Rich) mode produces output."""

    @patch("avos_cli.utils.output.is_interactive", return_value=True)
    def test_renders_without_error(self, _mock: object) -> None:
        render_table(
            "Rich Table",
            [("A", "bold"), ("B", "")],
            [["x", "y"]],
        )


class TestRenderPanelPlainText:
    """Validate render_panel in non-TTY mode."""

    @patch("avos_cli.utils.output.is_interactive", return_value=False)
    def test_renders_title_and_content(self, _mock: object, capsys: pytest.CaptureFixture[str]) -> None:
        render_panel("Status", "All good")
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "Status" in out
        assert "All good" in out


class TestRenderTreePlainText:
    """Validate render_tree in non-TTY mode."""

    @patch("avos_cli.utils.output.is_interactive", return_value=False)
    def test_renders_hierarchy(self, _mock: object, capsys: pytest.CaptureFixture[str]) -> None:
        render_tree("Root", [("Branch1", ["leaf1", "leaf2"]), ("Branch2", ["leaf3"])])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "Root" in out
        assert "Branch1" in out
        assert "leaf1" in out
        assert "leaf3" in out


class TestRenderKvPanelPlainText:
    """Validate render_kv_panel in non-TTY mode."""

    @patch("avos_cli.utils.output.is_interactive", return_value=False)
    def test_renders_key_value_pairs(self, _mock: object, capsys: pytest.CaptureFixture[str]) -> None:
        render_kv_panel("Info", [("Goal", "Fix bug"), ("Branch", "main")])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "Info" in out
        assert "Goal" in out
        assert "Fix bug" in out
        assert "Branch" in out

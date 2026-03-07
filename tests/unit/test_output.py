"""Tests for output formatting (print_json, print_verbose, create_progress).

Validates JSON envelope shape, verbose suppression, and progress bar suppression
per Sprint 6 WP-05 output contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avos_cli.utils.output import (
    create_progress,
    print_json,
    print_verbose,
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
        assert obj["error"]["message"] == "Bad key"
        assert obj["error"]["hint"] == "Check env"
        assert obj["error"]["retryable"] is False

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
            pass  # no-op, should not raise

    def test_suppress_does_not_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        progress = create_progress("Processing", suppress=True)
        with progress:
            pass
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "Processing" not in out or len(out.strip()) == 0


class TestGoldenOutput:
    """Validate output matches golden snapshots."""

    def test_json_success_matches_golden(self, capsys: pytest.CaptureFixture[str]) -> None:
        from pathlib import Path

        golden_path = Path(__file__).resolve().parents[1] / "golden" / "json_envelope_success.golden"
        expected = json.loads(golden_path.read_text().strip())
        print_json(success=True, data=expected["data"], error=None)
        captured = capsys.readouterr()
        actual = json.loads(captured.out.strip())
        assert actual["success"] == expected["success"]
        assert actual["data"] == expected["data"]
        assert actual["error"] is None


class TestGoldenOutput:
    """Validate output matches golden snapshots."""

    def test_json_success_matches_golden(
        self, capsys: pytest.CaptureFixture[str], tmp_path: pytest.TempPathFactory
    ) -> None:
        from pathlib import Path

        golden = Path(__file__).resolve().parents[2] / "golden" / "json_envelope_success.golden"
        if not golden.exists():
            pytest.skip(f"Golden file not found: {golden}")
        expected = golden.read_text().strip()
        print_json(success=True, data={"note_id": "abc-123", "status": "ok"}, error=None)
        captured = capsys.readouterr()
        actual = (captured.out + captured.err).strip()
        assert json.loads(actual) == json.loads(expected)


class TestGoldenOutput:
    """Validate output against golden snapshots."""

    def test_json_success_matches_golden(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pathlib import Path

        golden_path = Path(__file__).resolve().parents[1] / "golden" / "json_envelope_success.golden"
        expected = json.loads(golden_path.read_text().strip())
        print_json(success=True, data=expected["data"], error=None)
        captured = capsys.readouterr()
        actual = json.loads((captured.out + captured.err).strip())
        assert actual == expected


class TestGoldenOutput:
    """Validate output against golden snapshots."""

    def test_json_success_matches_golden(self, capsys: pytest.CaptureFixture[str]) -> None:
        from pathlib import Path

        golden_path = Path(__file__).resolve().parents[1] / "golden" / "json_envelope_success.golden"
        expected = json.loads(golden_path.read_text().strip())
        print_json(success=True, data=expected["data"], error=None)
        captured = capsys.readouterr()
        actual = json.loads((captured.out + captured.err).strip())
        assert actual == expected

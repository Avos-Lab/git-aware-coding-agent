"""Tests for AVOS-008: Shared utilities.

Covers time helpers, content hashing, output formatting, and logging.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from freezegun import freeze_time

from avos_cli.utils.dotenv_load import repository_root_env_path
from avos_cli.utils.hashing import content_hash
from avos_cli.utils.logger import RedactionFilter, get_logger
from avos_cli.utils.time_helpers import days_ago, is_within_ttl, parse_iso8601


class TestContentHash:
    """Verify SHA-256 content hashing is deterministic."""

    def test_same_input_same_hash(self):
        h1 = content_hash("hello world")
        h2 = content_hash("hello world")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = content_hash("hello")
        h2 = content_hash("world")
        assert h1 != h2

    def test_hash_is_hex_string(self):
        h = content_hash("test")
        assert isinstance(h, str)
        assert len(h) == 64
        int(h, 16)  # valid hex

    def test_empty_string(self):
        h = content_hash("")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_unicode_content(self):
        h1 = content_hash("unicode: \u00e9\u00e8\u00ea")
        h2 = content_hash("unicode: \u00e9\u00e8\u00ea")
        assert h1 == h2

    def test_multiline_content(self):
        content = "[type: raw_pr_thread]\n[repo: org/repo]\nTitle: Test"
        h1 = content_hash(content)
        h2 = content_hash(content)
        assert h1 == h2

    def test_whitespace_sensitivity(self):
        h1 = content_hash("hello world")
        h2 = content_hash("hello  world")
        assert h1 != h2


class TestTimeHelpers:
    @freeze_time("2026-03-06T12:00:00Z")
    def test_days_ago_returns_correct_date(self):
        result = days_ago(7)
        expected = datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    @freeze_time("2026-03-06T12:00:00Z")
    def test_days_ago_zero(self):
        result = days_ago(0)
        expected = datetime(2026, 3, 6, 12, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_is_within_ttl_recent(self):
        now = datetime.now(tz=timezone.utc)
        assert is_within_ttl(now.isoformat(), hours=24) is True

    def test_is_within_ttl_expired(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert is_within_ttl(old.isoformat(), hours=24) is False

    def test_parse_iso8601_with_z(self):
        dt = parse_iso8601("2026-01-15T10:30:00Z")
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 15
        assert dt.tzinfo is not None

    def test_parse_iso8601_with_offset(self):
        dt = parse_iso8601("2026-01-15T10:30:00+00:00")
        assert dt.tzinfo is not None

    def test_parse_iso8601_naive_gets_utc(self):
        dt = parse_iso8601("2026-01-15T10:30:00")
        assert dt.tzinfo is not None


class TestRedactionFilter:
    def _make_record(self, msg: str) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        return record

    def test_redacts_api_key_pattern(self):
        f = RedactionFilter()
        record = self._make_record("key=sk_live_abc123def456")
        f.filter(record)
        assert "sk_live_abc123def456" not in record.getMessage()
        assert "***REDACTED***" in record.getMessage()

    def test_redacts_github_token(self):
        f = RedactionFilter()
        record = self._make_record("token=ghp_abcdef1234567890abcdef1234567890abcd")
        f.filter(record)
        assert "ghp_abcdef1234567890" not in record.getMessage()

    def test_redacts_gho_token(self):
        f = RedactionFilter()
        record = self._make_record("token=gho_abcdef1234567890")
        f.filter(record)
        assert "gho_abcdef1234567890" not in record.getMessage()

    def test_preserves_normal_text(self):
        f = RedactionFilter()
        record = self._make_record("normal log message without secrets")
        f.filter(record)
        assert record.getMessage() == "normal log message without secrets"

    def test_returns_true(self):
        f = RedactionFilter()
        record = self._make_record("test")
        assert f.filter(record) is True


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test_component")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "avos.test_component"

    def test_logger_has_redaction_filter(self):
        logger = get_logger("test_redaction")
        has_redaction = any(isinstance(f, RedactionFilter) for f in logger.filters)
        assert has_redaction


class TestRepositoryRootEnvPath:
    """``repository_root_env_path`` points at root ``.env`` beside ``avos_cli``."""

    def test_basename_is_dotenv(self):
        path = repository_root_env_path()
        assert path.name == ".env"

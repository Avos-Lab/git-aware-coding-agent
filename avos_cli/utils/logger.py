"""Structured logging with secret redaction for AVOS CLI.

Provides a configured logger factory and a RedactionFilter that
masks API keys, tokens, and other sensitive patterns in log output.
Default level is INFO; DEBUG requires explicit --verbose opt-in.
"""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk_[a-zA-Z0-9_]{10,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{10,}"),
    re.compile(r"gho_[a-zA-Z0-9]{10,}"),
    re.compile(r"ghs_[a-zA-Z0-9]{10,}"),
    re.compile(r"ghu_[a-zA-Z0-9]{10,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{10,}"),
]

_REDACTED = "***REDACTED***"


class RedactionFilter(logging.Filter):
    """Logging filter that redacts known secret patterns from log messages.

    Covers Avos API keys (sk_*), GitHub tokens (ghp_*, gho_*, ghs_*, ghu_*),
    and GitHub fine-grained PATs (github_pat_*).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply redaction to the log record message.

        Args:
            record: The log record to filter.

        Returns:
            Always True (record is never suppressed, only sanitized).
        """
        msg = record.getMessage()
        redacted = msg
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(_REDACTED, redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def get_logger(component: str, level: int = logging.INFO) -> logging.Logger:
    """Create a configured logger for an AVOS CLI component.

    Args:
        component: Component name (e.g. 'memory_client', 'git_client').
        level: Logging level (default INFO).

    Returns:
        A Logger instance with redaction filter and structured formatter.
    """
    logger = logging.getLogger(f"avos.{component}")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if not any(isinstance(f, RedactionFilter) for f in logger.filters):
        logger.addFilter(RedactionFilter())

    return logger

"""Reference parser for PR and commit identifiers.

Provides regex-based parsing of various PR and commit reference formats
without LLM interpretation. Fails fast on ambiguous inputs.
"""

from __future__ import annotations

import re
from typing import ClassVar

from avos_cli.models.diff import DiffReferenceType, ParsedReference


class ReferenceParser:
    """Parses raw reference strings into structured ParsedReference objects.

    Supports formats:
    - PR: "PR #1245", "pr #1245", "PR#1245", "#1245", "org/repo#1245"
    - Commit: "Commit 8c3a1b2", "commit abc123", bare SHA (7-40 hex chars)
    - URLs: "https://github.com/org/repo/pull/123", ".../commit/abc123"
    """

    _PR_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # GitHub PR URL: https://github.com/org/repo/pull/123
        re.compile(
            r"(?:https?://)?github\.com/(?P<repo>[^/]+/[^/]+)/pull/(?P<num>\d+)",
            re.IGNORECASE,
        ),
        # org/repo#123 or github.com/org/repo#123
        re.compile(
            r"(?:github\.com/)?(?P<repo>[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)#(?P<num>\d+)",
            re.IGNORECASE,
        ),
        # PR #123 or PR#123 or pr #123
        re.compile(r"\bpr\s*#\s*(?P<num>\d+)", re.IGNORECASE),
        # Bare #123 (assumes PR in context)
        re.compile(r"^#(?P<num>\d+)(?:\s|$)"),
    ]

    _COMMIT_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # GitHub commit URL: https://github.com/org/repo/commit/abc123
        re.compile(
            r"(?:https?://)?github\.com/(?P<repo>[^/]+/[^/]+)/commit/(?P<sha>[a-f0-9]{7,40})",
            re.IGNORECASE,
        ),
        # Commit abc123 or commit: abc123
        re.compile(r"\bcommit:?\s*(?P<sha>[a-f0-9]{7,40})", re.IGNORECASE),
        # Bare SHA (7-40 hex chars, must be whole token)
        re.compile(r"^(?P<sha>[a-f0-9]{7,40})$", re.IGNORECASE),
    ]

    def parse(self, raw: str, default_repo: str | None) -> ParsedReference | None:
        """Parse a single raw reference string.

        Args:
            raw: The raw reference string to parse.
            default_repo: Default repository slug if not specified in reference.

        Returns:
            ParsedReference if successfully parsed, None otherwise.
        """
        if not raw or not raw.strip():
            return None

        text = raw.strip()

        # Try PR patterns first
        for pattern in self._PR_PATTERNS:
            match = pattern.search(text)
            if match:
                num_str = match.group("num")
                num = int(num_str)
                if num <= 0:
                    return None

                repo = match.groupdict().get("repo") or default_repo
                return ParsedReference(
                    reference_type=DiffReferenceType.PR,
                    raw_id=num_str,
                    repo_slug=repo,
                )

        # Try commit patterns
        for pattern in self._COMMIT_PATTERNS:
            match = pattern.search(text)
            if match:
                sha = match.group("sha").lower()
                repo = match.groupdict().get("repo") or default_repo
                return ParsedReference(
                    reference_type=DiffReferenceType.COMMIT,
                    raw_id=sha,
                    repo_slug=repo,
                )

        return None

    def parse_all(
        self, raw_list: list[str], default_repo: str | None
    ) -> list[ParsedReference]:
        """Parse multiple raw reference strings.

        Args:
            raw_list: List of raw reference strings to parse.
            default_repo: Default repository slug if not specified.

        Returns:
            List of successfully parsed references (invalid ones are skipped).
        """
        results: list[ParsedReference] = []
        for raw in raw_list:
            ref = self.parse(raw, default_repo)
            if ref is not None:
                results.append(ref)
        return results

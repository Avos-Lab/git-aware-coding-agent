"""Commit artifact builder.

Transforms CommitArtifact into canonical structured text for Avos Memory.
"""

from __future__ import annotations

from avos_cli.artifacts.base import BaseArtifactBuilder
from avos_cli.models.artifacts import CommitArtifact


class CommitBuilder(BaseArtifactBuilder):
    """Builds structured text from commit data."""

    def build(self, model: CommitArtifact) -> str:  # type: ignore[override]
        """Build structured text from a CommitArtifact.

        Args:
            model: Commit data.

        Returns:
            Canonical structured text.
        """
        lines: list[str] = []
        lines.append("[type: commit]")
        lines.append(f"[repo: {model.repo}]")
        lines.append(f"[hash: {model.hash}]")
        lines.append(f"[author: {model.author}]")
        lines.append(f"[date: {model.date}]")
        if model.files_changed:
            lines.append(f"[files: {', '.join(model.files_changed)}]")
        if model.diff_stats:
            lines.append(f"[diff: {model.diff_stats}]")
        lines.append(f"Message: {model.message}")
        return "\n".join(lines)

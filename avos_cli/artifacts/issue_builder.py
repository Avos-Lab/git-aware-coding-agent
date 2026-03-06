"""Issue artifact builder.

Transforms IssueArtifact into canonical structured text for Avos Memory.
"""

from __future__ import annotations

from avos_cli.artifacts.base import BaseArtifactBuilder
from avos_cli.models.artifacts import IssueArtifact


class IssueBuilder(BaseArtifactBuilder):
    """Builds structured text from issue data."""

    def build(self, model: IssueArtifact) -> str:  # type: ignore[override]
        """Build structured text from an IssueArtifact.

        Args:
            model: Issue data.

        Returns:
            Canonical structured text.
        """
        lines: list[str] = []
        lines.append("[type: issue]")
        lines.append(f"[repo: {model.repo}]")
        lines.append(f"[issue: #{model.issue_number}]")
        if model.labels:
            lines.append(f"[labels: {', '.join(model.labels)}]")
        lines.append(f"Title: {model.title}")
        if model.body:
            lines.append(f"Body: {model.body}")
        if model.comments:
            lines.append("Comments:")
            for comment in model.comments:
                lines.append(f"  - {comment}")
        return "\n".join(lines)

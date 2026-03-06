"""PR thread artifact builder.

Transforms PRArtifact into canonical structured text for Avos Memory.
"""

from __future__ import annotations

from avos_cli.artifacts.base import BaseArtifactBuilder
from avos_cli.models.artifacts import PRArtifact


class PRThreadBuilder(BaseArtifactBuilder):
    """Builds structured text from pull request data.

    Output format:
        [type: raw_pr_thread]
        [repo: org/repo]
        [pr: #123]
        [author: username]
        [merged: 2026-01-15]
        [files: path/a.py, path/b.py]
        Title: ...
        Description: ...
        Discussion: ...
    """

    def build(self, model: PRArtifact) -> str:  # type: ignore[override]
        """Build structured text from a PRArtifact.

        Args:
            model: Pull request data.

        Returns:
            Canonical structured text.
        """
        lines: list[str] = []
        lines.append("[type: raw_pr_thread]")
        lines.append(f"[repo: {model.repo}]")
        lines.append(f"[pr: #{model.pr_number}]")
        lines.append(f"[author: {model.author}]")
        if model.merged_date:
            lines.append(f"[merged: {model.merged_date}]")
        if model.files:
            lines.append(f"[files: {', '.join(model.files)}]")
        lines.append(f"Title: {model.title}")
        if model.description:
            lines.append(f"Description: {model.description}")
        if model.discussion:
            lines.append(f"Discussion: {model.discussion}")
        return "\n".join(lines)

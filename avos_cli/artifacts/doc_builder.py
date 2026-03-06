"""Document artifact builder.

Transforms DocArtifact into canonical structured text for Avos Memory.
"""

from __future__ import annotations

from avos_cli.artifacts.base import BaseArtifactBuilder
from avos_cli.models.artifacts import DocArtifact


class DocBuilder(BaseArtifactBuilder):
    """Builds structured text from document data."""

    def build(self, model: DocArtifact) -> str:  # type: ignore[override]
        """Build structured text from a DocArtifact.

        Args:
            model: Document data.

        Returns:
            Canonical structured text.
        """
        lines: list[str] = []
        lines.append("[type: document]")
        lines.append(f"[repo: {model.repo}]")
        lines.append(f"[path: {model.path}]")
        lines.append(f"[content_type: {model.content_type}]")
        lines.append(f"Content:\n{model.content}")
        return "\n".join(lines)

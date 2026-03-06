"""Session artifact builder.

Transforms SessionArtifact into canonical structured text for Avos Memory.
"""

from __future__ import annotations

from avos_cli.artifacts.base import BaseArtifactBuilder
from avos_cli.models.artifacts import SessionArtifact


class SessionBuilder(BaseArtifactBuilder):
    """Builds structured text from session data."""

    def build(self, model: SessionArtifact) -> str:  # type: ignore[override]
        """Build structured text from a SessionArtifact.

        Args:
            model: Session data.

        Returns:
            Canonical structured text.
        """
        lines: list[str] = []
        lines.append("[type: session]")
        lines.append(f"[session: {model.session_id}]")
        lines.append(f"Goal: {model.goal}")
        if model.files_modified:
            lines.append(f"Files modified: {', '.join(model.files_modified)}")
        if model.decisions:
            lines.append("Decisions:")
            for decision in model.decisions:
                lines.append(f"  - {decision}")
        if model.errors:
            lines.append("Errors:")
            for error in model.errors:
                lines.append(f"  - {error}")
        if model.resolution:
            lines.append(f"Resolution: {model.resolution}")
        if model.timeline:
            lines.append("Timeline:")
            for entry in model.timeline:
                lines.append(f"  - {entry}")
        return "\n".join(lines)

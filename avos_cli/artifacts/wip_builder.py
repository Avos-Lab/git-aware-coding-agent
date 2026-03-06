"""WIP (work-in-progress) artifact builder.

Transforms WIPArtifact into canonical structured text for Avos Memory.
"""

from __future__ import annotations

from avos_cli.artifacts.base import BaseArtifactBuilder
from avos_cli.models.artifacts import WIPArtifact


class WIPBuilder(BaseArtifactBuilder):
    """Builds structured text from work-in-progress data."""

    def build(self, model: WIPArtifact) -> str:  # type: ignore[override]
        """Build structured text from a WIPArtifact.

        Args:
            model: WIP activity data.

        Returns:
            Canonical structured text.
        """
        lines: list[str] = []
        lines.append("[type: wip_activity]")
        lines.append(f"[developer: {model.developer}]")
        lines.append(f"[branch: {model.branch}]")
        lines.append(f"[timestamp: {model.timestamp}]")
        if model.intent:
            lines.append(f"Intent: {model.intent}")
        if model.files_touched:
            lines.append(f"Files: {', '.join(model.files_touched)}")
        if model.diff_stats:
            lines.append(f"Diff: {model.diff_stats}")
        if model.symbols_touched:
            lines.append(f"Symbols: {', '.join(model.symbols_touched)}")
        if model.modules_touched:
            lines.append(f"Modules: {', '.join(model.modules_touched)}")
        if model.subsystems_touched:
            lines.append(f"Subsystems: {', '.join(model.subsystems_touched)}")
        return "\n".join(lines)

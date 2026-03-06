"""Base class for artifact builders.

Defines the interface that all artifact builders must implement:
build() to produce structured text, and content_hash() for
deterministic idempotency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from avos_cli.utils.hashing import content_hash

T = TypeVar("T", bound=BaseModel)


class BaseArtifactBuilder(ABC):
    """Abstract base for all artifact builders.

    Each builder transforms a Pydantic model into a canonical
    structured text format suitable for storage in Avos Memory.
    """

    @abstractmethod
    def build(self, model: BaseModel) -> str:
        """Transform a Pydantic model into structured text.

        Args:
            model: The input data model.

        Returns:
            Canonical structured text string.
        """

    def content_hash(self, model: BaseModel) -> str:
        """Compute a deterministic SHA-256 hash of the built output.

        Args:
            model: The input data model.

        Returns:
            64-character hex string of the SHA-256 digest.
        """
        return content_hash(self.build(model))

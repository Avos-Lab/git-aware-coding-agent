"""Public model re-exports for avos_cli.models.

Import key types from here for convenience:
    from avos_cli.models import RepoConfig, PRArtifact, SearchResult
"""

from avos_cli.models.api import NoteResponse, SearchHit, SearchRequest, SearchResult
from avos_cli.models.artifacts import (
    CommitArtifact,
    DocArtifact,
    IssueArtifact,
    PRArtifact,
    SessionArtifact,
)
from avos_cli.models.config import (
    LLMConfig,
    RepoConfig,
    SessionCheckpoint,
    SessionState,
    WatcherPidState,
)
from avos_cli.models.query import (
    BudgetResult,
    FallbackReason,
    GroundedCitation,
    GroundingStatus,
    QueryMode,
    QueryResultEnvelope,
    ReferenceType,
    RetrievedArtifact,
    SanitizationResult,
    SanitizedArtifact,
    SynthesisRequest,
    SynthesisResponse,
    TimelineEvent,
)

__all__ = [
    "CommitArtifact",
    "DocArtifact",
    "IssueArtifact",
    "LLMConfig",
    "NoteResponse",
    "PRArtifact",
    "RepoConfig",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
    "SessionArtifact",
    "SessionCheckpoint",
    "SessionState",
    "WatcherPidState",
    "BudgetResult",
    "FallbackReason",
    "GroundedCitation",
    "GroundingStatus",
    "QueryMode",
    "QueryResultEnvelope",
    "ReferenceType",
    "RetrievedArtifact",
    "SanitizationResult",
    "SanitizedArtifact",
    "SynthesisRequest",
    "SynthesisResponse",
    "TimelineEvent",
]

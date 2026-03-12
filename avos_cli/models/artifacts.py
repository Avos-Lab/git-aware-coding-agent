"""Artifact models for AVOS CLI.

These Pydantic models define the input shape for each artifact builder.
They carry no behavior -- builders consume them to produce structured text.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PRArtifact(BaseModel):
    """Pull request data for the PRThreadBuilder.

    Args:
        repo: Repository slug 'org/repo'.
        pr_number: Pull request number.
        title: PR title.
        author: PR author username.
        merged_date: Date the PR was merged (ISO format string, optional).
        files: List of file paths changed in the PR.
        description: PR body/description text.
        discussion: Aggregated comments and review discussion.
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    pr_number: int
    title: str
    author: str
    merged_date: str | None = None
    files: list[str] = []
    description: str | None = None
    discussion: str | None = None


class IssueArtifact(BaseModel):
    """Issue data for the IssueBuilder.

    Args:
        repo: Repository slug 'org/repo'.
        issue_number: Issue number.
        title: Issue title.
        labels: List of label strings.
        body: Issue body text.
        comments: List of comment strings.
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    issue_number: int
    title: str
    labels: list[str] = []
    body: str | None = None
    comments: list[str] = []


class CommitArtifact(BaseModel):
    """Commit data for the CommitBuilder.

    Args:
        repo: Repository slug 'org/repo'.
        hash: Commit hash (short or full).
        message: Commit message.
        author: Commit author name.
        date: Commit date (ISO format string).
        files_changed: List of file paths changed.
        diff_stats: Summary of lines added/removed.
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    hash: str
    message: str
    author: str
    date: str
    files_changed: list[str] = []
    diff_stats: str | None = None


class SessionArtifact(BaseModel):
    """Session data for the SessionBuilder.

    Args:
        session_id: Unique session identifier.
        goal: Session goal description.
        author: Developer identity from git config (name, optionally with email). Defaults to "unknown".
        files_modified: Files modified during the session.
        decisions: Key decisions made during the session.
        errors: Errors encountered during the session.
        resolution: How the session goal was resolved.
        timeline: Chronological event entries.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    goal: str
    author: str = ""
    files_modified: list[str] = []
    decisions: list[str] = []
    errors: list[str] = []
    resolution: str | None = None
    timeline: list[str] = []


class DocArtifact(BaseModel):
    """Documentation data for the DocBuilder.

    Args:
        repo: Repository slug 'org/repo'.
        path: File path of the document within the repo.
        content_type: Type of document (e.g. 'readme', 'adr', 'design_doc').
        content: Full text content of the document.
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    path: str
    content_type: str
    content: str

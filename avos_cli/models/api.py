"""API request and response models for the Avos Memory API.

These models define the typed contracts for communication with the
closed-source Avos Memory API (search, add_memory, delete_note).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    """Search request payload for the Avos Memory API.

    Args:
        query: Natural language search query (min 1 char).
        k: Number of results to return (1-50, default 5).
        mode: Search strategy -- 'semantic', 'keyword', or 'hybrid'.
    """

    model_config = ConfigDict(frozen=True)

    query: str = Field(..., min_length=1)
    k: int = Field(default=5, ge=1, le=50)
    mode: Literal["semantic", "keyword", "hybrid"] = "semantic"


class SearchHit(BaseModel):
    """A single search result from the Avos Memory API.

    Args:
        note_id: Unique identifier for the matched note.
        content: Full text content of the note.
        created_at: ISO 8601 creation timestamp.
        rank: Relevance rank (1 = best match).
    """

    model_config = ConfigDict(frozen=True)

    note_id: str
    content: str
    created_at: str
    rank: int


class SearchResult(BaseModel):
    """Search response from the Avos Memory API.

    Args:
        results: List of search hits ordered by relevance.
        total_count: Total number of notes in the memory.
    """

    model_config = ConfigDict(frozen=True)

    results: list[SearchHit]
    total_count: int


class NoteResponse(BaseModel):
    """Response from add_memory (note creation) in the Avos Memory API.

    Args:
        note_id: Unique identifier for the created note.
        content: Text content of the note (or auto-generated description for media).
        created_at: ISO 8601 server-side creation timestamp.
    """

    model_config = ConfigDict(frozen=True)

    note_id: str
    content: str
    created_at: str

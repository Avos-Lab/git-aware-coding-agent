"""HTTP client wrapper for the Avos Memory API.

Provides add_memory, search, and delete_note operations with
retry logic, rate limit handling, and secret-safe logging.
This is the single integration point between the CLI and the
closed-source Avos Memory API.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from avos_cli.exceptions import (
    AuthError,
    RequestContractError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import NoteResponse, SearchResult
from avos_cli.utils.logger import get_logger

_log = get_logger("memory_client")

_DEFAULT_TIMEOUT = 30.0
_UPLOAD_TIMEOUT = 120.0
_MAX_RETRIES = 3


class _RetryableError(Exception):
    """Internal marker for errors that should trigger retry."""


class AvosMemoryClient:
    """HTTP client for the Avos Memory API.

    Wraps add_memory, search, and delete_note with auth injection,
    retry logic, rate limit handling, and typed error mapping.

    Args:
        api_key: Avos Memory API key.
        api_url: Base URL for the Avos Memory API.
    """

    def __init__(self, api_key: str, api_url: str) -> None:
        if not api_key:
            raise AuthError("API key is required for Avos Memory API", service="Avos Memory")
        self._api_key = api_key
        self._api_url = api_url.rstrip("/")
        self._client = httpx.Client(
            headers={"X-API-Key": api_key},
            timeout=_DEFAULT_TIMEOUT,
        )

    def add_memory(
        self,
        memory_id: str,
        content: str | None = None,
        files: list[str] | None = None,
        media: list[dict[str, str]] | None = None,
        event_at: str | None = None,
    ) -> NoteResponse:
        """Store a note in Avos Memory.

        Exactly one payload mode must be provided (text, file, or media).

        Args:
            memory_id: Target memory identifier.
            content: Text content for text mode.
            files: File paths for file upload mode.
            media: Media descriptors for media mode.
            event_at: Optional ISO 8601 timestamp for the event.

        Returns:
            NoteResponse with note_id, content, and created_at.

        Raises:
            RequestContractError: If payload modes are mixed or missing.
            AuthError: If authentication fails.
            UpstreamUnavailableError: If the API is unreachable after retries.
        """
        modes = sum(1 for m in [content, files, media] if m)
        if modes == 0:
            raise RequestContractError(
                "add_memory requires at least one of: content, files, or media"
            )
        if modes > 1:
            raise RequestContractError(
                "Payload modes are mutually exclusive: provide only one of content, files, or media"
            )

        if files:
            return self._upload_file(memory_id, files, event_at)
        elif media:
            return self._add_json(memory_id, content=content, media=media, event_at=event_at)
        else:
            return self._add_json(memory_id, content=content, event_at=event_at)

    def _add_json(
        self,
        memory_id: str,
        content: str | None = None,
        media: list[dict[str, str]] | None = None,
        event_at: str | None = None,
    ) -> NoteResponse:
        """Send a JSON note (text or media URL mode)."""
        url = f"{self._api_url}/api/v1/memories/{memory_id}/notes"
        body: dict[str, object] = {}
        if content is not None:
            body["content"] = content
        if media is not None:
            body["media"] = media
        if event_at is not None:
            body["event_at"] = event_at

        response = self._request_with_retry("POST", url, json=body)
        self._check_auth(response)
        self._check_response(response)
        return NoteResponse(**response.json())

    def _upload_file(
        self,
        memory_id: str,
        file_paths: list[str],
        event_at: str | None = None,
    ) -> NoteResponse:
        """Upload files via multipart form."""
        url = f"{self._api_url}/api/v1/memories/{memory_id}/notes/upload"
        files_data: list[tuple[str, tuple[str, bytes, str]]] = []
        for fp in file_paths:
            path = Path(fp)
            files_data.append(("files", (path.name, path.read_bytes(), "application/octet-stream")))

        response = self._request_with_retry(
            "POST", url, files=files_data, timeout=_UPLOAD_TIMEOUT
        )
        self._check_auth(response)
        self._check_response(response)
        return NoteResponse(**response.json())

    def search(
        self,
        memory_id: str,
        query: str,
        k: int = 5,
        mode: str = "semantic",
    ) -> SearchResult:
        """Search Avos Memory for relevant notes.

        Args:
            memory_id: Memory to search.
            query: Natural language search query.
            k: Number of results (1-50).
            mode: Search mode ('semantic', 'keyword', 'hybrid').

        Returns:
            SearchResult with ranked results and total_count.
        """
        url = f"{self._api_url}/api/v1/memories/{memory_id}/search"
        body = {"query": query, "k": k, "mode": mode}

        response = self._request_with_retry("POST", url, json=body)
        self._check_auth(response)
        self._check_response(response)
        return SearchResult(**response.json())

    def delete_note(self, memory_id: str, note_id: str) -> bool:
        """Delete a note from Avos Memory.

        Args:
            memory_id: Memory containing the note.
            note_id: ID of the note to delete.

        Returns:
            True if deleted (204), False if not found (404).
        """
        url = f"{self._api_url}/api/v1/memories/{memory_id}/notes/{note_id}"
        response = self._request_with_retry("DELETE", url)

        if response.status_code == 204:
            return True
        if response.status_code == 404:
            return False

        self._check_auth(response)
        self._check_response(response)
        return False

    def _request_with_retry(
        self,
        method: str,
        url: str,
        json: dict[str, object] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Wrapper that converts exhausted retries to UpstreamUnavailableError."""
        try:
            return self._request_with_retry_inner(method, url, json=json, files=files, timeout=timeout)
        except _RetryableError as e:
            raise UpstreamUnavailableError(
                f"Avos Memory API unavailable after {_MAX_RETRIES} retries: {e}"
            ) from e

    @retry(
        retry=retry_if_exception_type(_RetryableError),
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=wait_exponential(multiplier=0.5, min=0.1, max=10),
        reraise=True,
    )
    def _request_with_retry_inner(
        self,
        method: str,
        url: str,
        json: dict[str, object] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request with retry on transient failures.

        Retries on 429, 503, and connection errors up to MAX_RETRIES times.
        Respects retry_after from response body when available.
        """
        try:
            response = self._client.request(
                method,
                url,
                json=json,
                files=files,
                timeout=timeout or _DEFAULT_TIMEOUT,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            _log.warning("Connection error to %s: %s", url, type(e).__name__)
            raise _RetryableError(str(e)) from e

        if response.status_code in (429, 503):
            retry_after = self._extract_retry_after(response)
            if retry_after and retry_after > 0:
                _log.info("Rate limited, waiting %.1fs", retry_after)
                time.sleep(min(retry_after, 30))
            raise _RetryableError(f"HTTP {response.status_code}")

        return response

    def _extract_retry_after(self, response: httpx.Response) -> float | None:
        """Extract retry_after value from response body or headers."""
        try:
            data = response.json()
            if "retry_after" in data:
                return float(data["retry_after"])
        except Exception:
            pass
        header = response.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return None

    def _check_auth(self, response: httpx.Response) -> None:
        """Raise AuthError on 401/403 responses."""
        if response.status_code in (401, 403):
            raise AuthError(
                f"Authentication failed (HTTP {response.status_code})",
                service="Avos Memory",
            )

    def _check_response(self, response: httpx.Response) -> None:
        """Raise UpstreamUnavailableError on unexpected error responses."""
        if response.status_code >= 400:
            raise UpstreamUnavailableError(
                f"Avos Memory API error: HTTP {response.status_code}"
            )

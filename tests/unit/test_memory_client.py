"""Tests for AVOS-004: Avos Memory Client.

Uses respx to mock httpx requests. Covers add_memory, search, delete_note,
retry behavior, rate limiting, auth errors, and mode exclusivity.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from avos_cli.exceptions import AuthError, RequestContractError, UpstreamUnavailableError
from avos_cli.services.memory_client import AvosMemoryClient

BASE_URL = "https://api.test.com"
API_KEY = "sk_test_key_12345"
MEMORY_ID = "repo:org/repo"


@pytest.fixture()
def client() -> AvosMemoryClient:
    return AvosMemoryClient(api_key=API_KEY, api_url=BASE_URL)


class TestAddMemoryText:
    @respx.mock
    def test_add_text_note(self, client: AvosMemoryClient):
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/notes").mock(
            return_value=httpx.Response(
                201,
                json={
                    "note_id": "abc-123",
                    "content": "test content",
                    "created_at": "2026-01-15T10:00:00",
                },
            )
        )
        result = client.add_memory(MEMORY_ID, content="test content")
        assert result.note_id == "abc-123"
        assert result.content == "test content"

    @respx.mock
    def test_add_text_with_event_at(self, client: AvosMemoryClient):
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/notes").mock(
            return_value=httpx.Response(
                201,
                json={
                    "note_id": "abc-123",
                    "content": "test",
                    "created_at": "2026-01-15T10:00:00",
                },
            )
        )
        result = client.add_memory(
            MEMORY_ID, content="test", event_at="2026-01-15T10:00:00Z"
        )
        assert result.note_id == "abc-123"


class TestAddMemoryFile:
    @respx.mock
    def test_add_file_upload(self, client: AvosMemoryClient, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")

        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/notes/upload").mock(
            return_value=httpx.Response(
                201,
                json={
                    "note_id": "file-123",
                    "content": "file content",
                    "created_at": "2026-01-15T10:00:00",
                },
            )
        )
        result = client.add_memory(MEMORY_ID, files=[str(test_file)])
        assert result.note_id == "file-123"


class TestModeExclusivity:
    def test_rejects_mixed_content_and_files(self, client: AvosMemoryClient):
        with pytest.raises(RequestContractError, match="mutually exclusive"):
            client.add_memory(MEMORY_ID, content="text", files=["file.txt"])

    def test_rejects_mixed_content_and_media(self, client: AvosMemoryClient):
        with pytest.raises(RequestContractError, match="mutually exclusive"):
            client.add_memory(
                MEMORY_ID,
                content="text",
                media=[{"url": "https://example.com/video.mp4"}],
            )

    def test_rejects_no_payload(self, client: AvosMemoryClient):
        with pytest.raises(RequestContractError, match="at least one"):
            client.add_memory(MEMORY_ID)


class TestSearch:
    @respx.mock
    def test_search_returns_results(self, client: AvosMemoryClient):
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "note_id": "hit-1",
                            "content": "matching content",
                            "created_at": "2026-01-15T10:00:00Z",
                            "rank": 1,
                        }
                    ],
                    "total_count": 42,
                },
            )
        )
        result = client.search(MEMORY_ID, query="test query", k=5, mode="semantic")
        assert len(result.results) == 1
        assert result.results[0].note_id == "hit-1"
        assert result.total_count == 42

    @respx.mock
    def test_search_empty_results(self, client: AvosMemoryClient):
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(
                200,
                json={"results": [], "total_count": 0},
            )
        )
        result = client.search(MEMORY_ID, query="nothing")
        assert result.results == []


class TestDeleteNote:
    @respx.mock
    def test_delete_returns_true_on_204(self, client: AvosMemoryClient):
        respx.delete(
            f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/notes/note-123"
        ).mock(return_value=httpx.Response(204))
        assert client.delete_note(MEMORY_ID, "note-123") is True

    @respx.mock
    def test_delete_returns_false_on_404(self, client: AvosMemoryClient):
        respx.delete(
            f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/notes/missing"
        ).mock(return_value=httpx.Response(404, json={"detail": "Not found"}))
        assert client.delete_note(MEMORY_ID, "missing") is False


class TestAuthErrors:
    @respx.mock
    def test_401_raises_auth_error(self, client: AvosMemoryClient):
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(
                401,
                json={"error": "Unauthorized", "code": "UNAUTHORIZED"},
            )
        )
        with pytest.raises(AuthError):
            client.search(MEMORY_ID, query="test")

    def test_missing_api_key_raises(self):
        with pytest.raises(AuthError, match="API key"):
            AvosMemoryClient(api_key="", api_url=BASE_URL)


class TestRetryBehavior:
    @respx.mock
    def test_retries_on_503(self, client: AvosMemoryClient):
        route = respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search")
        route.side_effect = [
            httpx.Response(503, json={"error": "Service unavailable"}),
            httpx.Response(
                200,
                json={"results": [], "total_count": 0},
            ),
        ]
        result = client.search(MEMORY_ID, query="test")
        assert result.results == []
        assert route.call_count == 2

    @respx.mock
    def test_retries_on_429(self, client: AvosMemoryClient):
        route = respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search")
        route.side_effect = [
            httpx.Response(429, json={"error": "Rate limited", "retry_after": 0}),
            httpx.Response(
                200,
                json={"results": [], "total_count": 0},
            ),
        ]
        result = client.search(MEMORY_ID, query="test")
        assert result.results == []

    @respx.mock
    def test_raises_after_max_retries(self, client: AvosMemoryClient):
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(503, json={"error": "down"})
        )
        with pytest.raises(UpstreamUnavailableError):
            client.search(MEMORY_ID, query="test")


class TestApiKeyHeader:
    @respx.mock
    def test_sends_api_key_header(self, client: AvosMemoryClient):
        route = respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(
                200,
                json={"results": [], "total_count": 0},
            )
        )
        client.search(MEMORY_ID, query="test")
        assert route.calls[0].request.headers["x-api-key"] == API_KEY

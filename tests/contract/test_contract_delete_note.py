"""Contract tests for delete_note API boundary.

Validates DELETE request, 204 success, and 404 not-found at HTTP
transport level using respx.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from avos_cli.exceptions import AuthError
from avos_cli.services.memory_client import AvosMemoryClient, _normalize_memory_id_for_api

BASE_URL = "https://api.contract.test"
API_KEY = "sk_contract_test_key"
MEMORY_ID = "repo:org/repo"
MEMORY_ID_API = _normalize_memory_id_for_api(MEMORY_ID)
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    return path.read_text()


@pytest.fixture()
def client() -> AvosMemoryClient:
    return AvosMemoryClient(api_key=API_KEY, api_url=BASE_URL)


@pytest.mark.contract
class TestDeleteNoteContractSuccess:
    """Validate delete_note success contract (204)."""

    @respx.mock
    def test_delete_204_returns_true(self, client: AvosMemoryClient) -> None:
        respx.delete(
            f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes/note-abc"
        ).mock(return_value=httpx.Response(204))
        assert client.delete_note(MEMORY_ID, "note-abc") is True

    @respx.mock
    def test_delete_request_url_shape(self, client: AvosMemoryClient) -> None:
        route = respx.delete(
            f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes/xyz-123"
        ).mock(return_value=httpx.Response(204))
        client.delete_note(MEMORY_ID, "xyz-123")
        assert route.calls[0].request.url.path.endswith("/notes/xyz-123")


@pytest.mark.contract
class TestDeleteNoteContractErrors:
    """Validate delete_note error responses."""

    @respx.mock
    def test_delete_404_returns_false(self, client: AvosMemoryClient) -> None:
        respx.delete(
            f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes/missing"
        ).mock(return_value=httpx.Response(404, json={"detail": "Not found"}))
        assert client.delete_note(MEMORY_ID, "missing") is False

    @respx.mock
    def test_delete_401_raises_auth_error(self, client: AvosMemoryClient) -> None:
        import json

        err = json.loads((FIXTURES_DIR / "error_401.json").read_text())
        respx.delete(
            f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes/some-note"
        ).mock(return_value=httpx.Response(401, json=err))
        with pytest.raises(AuthError):
            client.delete_note(MEMORY_ID, "some-note")

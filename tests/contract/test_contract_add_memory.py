"""Contract tests for add_memory API boundary.

Validates POST request shape, 201 success envelope, and error responses
(401, 403, 422, 429, 503) at HTTP transport level using respx.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from avos_cli.exceptions import AuthError, RequestContractError, UpstreamUnavailableError
from avos_cli.services.memory_client import AvosMemoryClient, _normalize_memory_id_for_api

BASE_URL = "https://api.contract.test"
API_KEY = "sk_contract_test_key"
MEMORY_ID = "repo:org/repo"
MEMORY_ID_API = _normalize_memory_id_for_api(MEMORY_ID)
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text())


@pytest.fixture()
def client() -> AvosMemoryClient:
    return AvosMemoryClient(api_key=API_KEY, api_url=BASE_URL)


@pytest.mark.contract
class TestAddMemoryContractSuccess:
    """Validate add_memory success contract (201)."""

    @respx.mock
    def test_post_json_shape_and_201_success(self, client: AvosMemoryClient) -> None:
        fixture = _load_fixture("add_memory_success.json")
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes").mock(
            return_value=httpx.Response(201, json=fixture)
        )
        result = client.add_memory(MEMORY_ID, content="test content")
        assert result.note_id == fixture["note_id"]
        assert result.content == fixture["content"]
        assert result.created_at == fixture["created_at"]

    @respx.mock
    def test_request_has_content_in_body(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes").mock(
            return_value=httpx.Response(201, json=_load_fixture("add_memory_success.json"))
        )
        client.add_memory(MEMORY_ID, content="payload content")
        req = respx.calls[0].request
        body = json.loads(req.content)
        assert body["content"] == "payload content"


@pytest.mark.contract
class TestAddMemoryContractErrors:
    """Validate add_memory error envelopes (401, 403, 422, 429, 503)."""

    @respx.mock
    def test_401_raises_auth_error(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes").mock(
            return_value=httpx.Response(401, json=_load_fixture("error_401.json"))
        )
        with pytest.raises(AuthError):
            client.add_memory(MEMORY_ID, content="test")

    @respx.mock
    def test_403_raises_auth_error(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes").mock(
            return_value=httpx.Response(403, json=_load_fixture("error_403.json"))
        )
        with pytest.raises(AuthError):
            client.add_memory(MEMORY_ID, content="test")

    @respx.mock
    def test_422_raises_upstream_error(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes").mock(
            return_value=httpx.Response(422, json=_load_fixture("error_422.json"))
        )
        with pytest.raises(UpstreamUnavailableError):
            client.add_memory(MEMORY_ID, content="test")

    @respx.mock
    def test_429_retries_then_succeeds(self, client: AvosMemoryClient) -> None:
        fixture = _load_fixture("add_memory_success.json")
        route = respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes")
        route.side_effect = [
            httpx.Response(429, json=_load_fixture("error_429.json")),
            httpx.Response(201, json=fixture),
        ]
        result = client.add_memory(MEMORY_ID, content="test")
        assert result.note_id == fixture["note_id"]

    @respx.mock
    def test_503_raises_after_retries(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID_API}/notes").mock(
            return_value=httpx.Response(503, json=_load_fixture("error_503.json"))
        )
        with pytest.raises(UpstreamUnavailableError):
            client.add_memory(MEMORY_ID, content="test")


@pytest.mark.contract
class TestAddMemoryContractValidation:
    """Validate request contract (payload modes)."""

    def test_rejects_empty_content(self, client: AvosMemoryClient) -> None:
        with pytest.raises(RequestContractError, match="at least one"):
            client.add_memory(MEMORY_ID)

    def test_rejects_mixed_content_and_files(self, client: AvosMemoryClient) -> None:
        with pytest.raises(RequestContractError, match="mutually exclusive"):
            client.add_memory(MEMORY_ID, content="x", files=["a.txt"])

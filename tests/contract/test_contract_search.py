"""Contract tests for search API boundary.

Validates POST request shape, success envelope, and error responses
(401, 404, 422) at HTTP transport level using respx.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from avos_cli.exceptions import AuthError, UpstreamUnavailableError
from avos_cli.services.memory_client import AvosMemoryClient

BASE_URL = "https://api.contract.test"
API_KEY = "sk_contract_test_key"
MEMORY_ID = "repo:org/repo"
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text())


@pytest.fixture()
def client() -> AvosMemoryClient:
    return AvosMemoryClient(api_key=API_KEY, api_url=BASE_URL)


@pytest.mark.contract
class TestSearchContractSuccess:
    """Validate search success contract."""

    @respx.mock
    def test_post_shape_and_success_envelope(self, client: AvosMemoryClient) -> None:
        fixture = _load_fixture("search_success.json")
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        result = client.search(MEMORY_ID, query="test query", k=5, mode="semantic")
        assert len(result.results) == len(fixture["results"])
        assert result.total_count == fixture["total_count"]
        for i, hit in enumerate(result.results):
            assert hit.note_id == fixture["results"][i]["note_id"]
            assert hit.content == fixture["results"][i]["content"]
            assert hit.rank == fixture["results"][i]["rank"]

    @respx.mock
    def test_empty_results_envelope(self, client: AvosMemoryClient) -> None:
        fixture = _load_fixture("search_empty.json")
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        result = client.search(MEMORY_ID, query="nonexistent")
        assert result.results == []
        assert result.total_count == 0

    @respx.mock
    def test_request_has_query_k_mode(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(200, json=_load_fixture("search_empty.json"))
        )
        client.search(MEMORY_ID, query="my query", k=10, mode="hybrid")
        req = respx.calls[0].request
        body = json.loads(req.content)
        assert body["query"] == "my query"
        assert body["k"] == 10
        assert body["mode"] == "hybrid"


@pytest.mark.contract
class TestSearchContractErrors:
    """Validate search error envelopes."""

    @respx.mock
    def test_401_raises_auth_error(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(401, json=_load_fixture("error_401.json"))
        )
        with pytest.raises(AuthError):
            client.search(MEMORY_ID, query="test")

    @respx.mock
    def test_404_raises_upstream_error(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(404, json={"detail": "Memory not found"})
        )
        with pytest.raises(UpstreamUnavailableError):
            client.search(MEMORY_ID, query="test")

    @respx.mock
    def test_422_raises_upstream_error(self, client: AvosMemoryClient) -> None:
        respx.post(f"{BASE_URL}/api/v1/memories/{MEMORY_ID}/search").mock(
            return_value=httpx.Response(422, json=_load_fixture("error_422.json"))
        )
        with pytest.raises(UpstreamUnavailableError):
            client.search(MEMORY_ID, query="test")

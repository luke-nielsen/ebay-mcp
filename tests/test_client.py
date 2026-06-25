"""Tests for the eBay Browse API client.

An httpx ``MockTransport`` stands in for eBay: it answers the OAuth token
endpoint and the Browse search/item endpoints, and records the requests so we can
assert the filter/sort grammar and header construction. Backoff sleeps are
neutralised so retry paths run instantly.
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ebay_mcp.client import EbayClient
from ebay_mcp.errors import EbayAPIError, EbayError

ITEM_JSON = {
    "itemId": "v1|1|0",
    "title": "Test Item",
    "price": {"value": "25.00", "currency": "USD"},
    "condition": "New",
}


class FakeEbay:
    """A scriptable eBay backend for MockTransport."""

    def __init__(self, *, search_status: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.search_status = search_status or [200]
        self._search_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        if path.endswith("/item_summary/search"):
            self.requests.append(request)
            status = self.search_status[min(self._search_calls, len(self.search_status) - 1)]
            self._search_calls += 1
            if status == 200:
                return httpx.Response(200, json={"total": 1, "itemSummaries": [ITEM_JSON]})
            return httpx.Response(status, json={"errors": [{"message": f"boom {status}"}]})
        if "/item/" in path:
            self.requests.append(request)
            return httpx.Response(200, json=ITEM_JSON)
        return httpx.Response(404, json={"errors": [{"message": "not found"}]})


def _client(config, fake: FakeEbay) -> EbayClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    client = EbayClient(config, http=http)

    async def _no_sleep(*args, **kwargs):
        return None

    client._backoff = _no_sleep  # type: ignore[method-assign]
    return client


def _last_search_params(fake: FakeEbay) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(fake.requests[-1].url)).query)


def test_search_parses_results(config):
    fake = FakeEbay()

    async def run() -> None:
        async with _client(config, fake) as client:
            result = await client.search("camera", limit=5)
        assert result.total == 1
        assert result.items[0].title == "Test Item"
        params = _last_search_params(fake)
        assert params["q"] == ["camera"]
        assert params["limit"] == ["5"]
        # Marketplace header is attached.
        assert fake.requests[-1].headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
        assert fake.requests[-1].headers["Authorization"] == "Bearer tok"

    asyncio.run(run())


def test_search_builds_price_and_condition_filter(config):
    fake = FakeEbay()

    async def run() -> None:
        async with _client(config, fake) as client:
            await client.search("phone", min_price=50, max_price=200, condition="used")
        flt = _last_search_params(fake)["filter"][0]
        assert "price:[50..200]" in flt
        assert "priceCurrency:USD" in flt
        assert "conditions:{USED}" in flt

    asyncio.run(run())


def test_search_maps_sort(config):
    fake = FakeEbay()

    async def run() -> None:
        async with _client(config, fake) as client:
            await client.search("tv", sort="price_desc")
        assert _last_search_params(fake)["sort"] == ["-price"]

    asyncio.run(run())


def test_best_match_sort_is_omitted(config):
    fake = FakeEbay()

    async def run() -> None:
        async with _client(config, fake) as client:
            await client.search("tv", sort="best_match")
        assert "sort" not in _last_search_params(fake)

    asyncio.run(run())


def test_invalid_sort_and_condition_rejected(config):
    fake = FakeEbay()

    async def run() -> None:
        async with _client(config, fake) as client:
            with pytest.raises(EbayError):
                await client.search("tv", sort="cheapest")
            with pytest.raises(EbayError):
                await client.search("tv", condition="mint")
            with pytest.raises(EbayError):
                await client.search("   ")

    asyncio.run(run())


def test_retries_then_succeeds_on_500(config):
    fake = FakeEbay(search_status=[500, 500, 200])

    async def run() -> None:
        async with _client(config, fake) as client:
            result = await client.search("retry")
        assert result.total == 1
        assert len(fake.requests) == 3

    asyncio.run(run())


def test_gives_up_after_max_retries(config):
    fake = FakeEbay(search_status=[503])

    async def run() -> None:
        async with _client(config, fake) as client:
            with pytest.raises(EbayAPIError) as info:
                await client.search("always-fails")
        assert info.value.status_code == 503

    asyncio.run(run())


def test_get_item(config):
    fake = FakeEbay()

    async def run() -> None:
        async with _client(config, fake) as client:
            item = await client.get_item("v1|1|0")
        assert item.item_id == "v1|1|0"
        assert "/item/v1|1|0" in str(fake.requests[-1].url)

    asyncio.run(run())

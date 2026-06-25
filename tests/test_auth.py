"""Tests for OAuth token caching and refresh.

A controllable monotonic clock and an httpx ``MockTransport`` let us assert the
caching contract precisely: one token request per refresh, reuse while fresh,
refresh near expiry, and a single request under concurrent access.
"""

from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from ebay_mcp.auth import TokenManager
from ebay_mcp.errors import EbayAuthError


def _token_transport(counter: dict[str, int], *, expires_in: int = 7200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter["calls"] += 1
        # Verify Basic auth header is well-formed.
        auth = request.headers["Authorization"]
        assert auth.startswith("Basic ")
        decoded = base64.b64decode(auth.removeprefix("Basic ")).decode()
        assert decoded == "test-client-id:test-client-secret"
        return httpx.Response(
            200,
            json={
                "access_token": f"token-{counter['calls']}",
                "expires_in": expires_in,
                "token_type": "Application Access Token",
            },
        )

    return httpx.MockTransport(handler)


def _with_clock(manager: TokenManager, clock: list[float]) -> None:
    manager._now = lambda: clock[0]  # type: ignore[method-assign]


def test_token_is_cached(config):
    counter = {"calls": 0}

    async def run() -> None:
        async with httpx.AsyncClient(transport=_token_transport(counter)) as http:
            manager = TokenManager(config, http)
            clock = [0.0]
            _with_clock(manager, clock)

            assert await manager.get_token() == "token-1"
            clock[0] = 100.0  # still well within the 7200s lifetime
            assert await manager.get_token() == "token-1"
            assert counter["calls"] == 1

    asyncio.run(run())


def test_token_refreshes_near_expiry(config):
    counter = {"calls": 0}

    async def run() -> None:
        async with httpx.AsyncClient(transport=_token_transport(counter, expires_in=100)) as http:
            manager = TokenManager(config, http)
            clock = [0.0]
            _with_clock(manager, clock)

            assert await manager.get_token() == "token-1"
            # Past (expiry - leeway): 100 - 60 = 40.
            clock[0] = 50.0
            assert await manager.get_token() == "token-2"
            assert counter["calls"] == 2

    asyncio.run(run())


def test_concurrent_requests_trigger_single_fetch(config):
    counter = {"calls": 0}

    async def run() -> None:
        async with httpx.AsyncClient(transport=_token_transport(counter)) as http:
            manager = TokenManager(config, http)
            _with_clock(manager, [0.0])
            tokens = await asyncio.gather(*(manager.get_token() for _ in range(10)))
            assert set(tokens) == {"token-1"}
            assert counter["calls"] == 1

    asyncio.run(run())


def test_bad_credentials_raise(config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_client"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            manager = TokenManager(config, http)
            with pytest.raises(EbayAuthError):
                await manager.get_token()

    asyncio.run(run())

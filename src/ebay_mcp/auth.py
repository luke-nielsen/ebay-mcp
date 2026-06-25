"""OAuth2 client-credentials token management for the eBay Browse API.

The Browse API's public search endpoints authenticate with an *application*
access token obtained via the client-credentials grant. Tokens last two hours, so
we cache one and refresh it just before expiry rather than minting a new token on
every request.

Concurrency: tool calls run on the server's event loop and may overlap. An
:class:`asyncio.Lock` guards the refresh so that N concurrent calls arriving with
an expired token trigger exactly one token request, not N. A monotonic clock is
used for expiry so the cache is immune to wall-clock adjustments.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass

import httpx

from .config import Config
from .errors import EbayAuthError


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    expires_at: float  # monotonic seconds

    def is_fresh(self, now: float, leeway: float) -> bool:
        return now < (self.expires_at - leeway)


class TokenManager:
    """Fetches and caches an eBay application access token."""

    def __init__(self, config: Config, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http
        self._lock = asyncio.Lock()
        self._token: _Token | None = None

    @staticmethod
    def _basic_auth_header(config: Config) -> str:
        raw = f"{config.client_id}:{config.client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _now(self) -> float:
        return time.monotonic()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing it if necessary."""

        cached = self._token
        if not force_refresh and cached and cached.is_fresh(self._now(), self._config.token_leeway):
            return cached.value

        async with self._lock:
            # Re-check under the lock: another coroutine may have refreshed while
            # we were waiting to acquire it.
            cached = self._token
            if (
                not force_refresh
                and cached
                and cached.is_fresh(self._now(), self._config.token_leeway)
            ):
                return cached.value
            self._token = await self._fetch_token()
            return self._token.value

    async def _fetch_token(self) -> _Token:
        self._config.require_credentials()
        headers = {
            "Authorization": self._basic_auth_header(self._config),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body = {
            "grant_type": "client_credentials",
            "scope": " ".join(self._config.scopes),
        }
        try:
            response = await self._http.post(
                self._config.oauth_token_url,
                headers=headers,
                data=body,
                timeout=self._config.timeout,
            )
        except httpx.HTTPError as exc:  # network-level failure
            raise EbayAuthError(f"Token request failed: {exc}") from exc

        if response.status_code != 200:
            raise EbayAuthError(
                f"Token request rejected (HTTP {response.status_code}): {_safe_body(response)}"
            )

        payload = response.json()
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not access_token or not isinstance(expires_in, (int, float)):
            raise EbayAuthError(f"Malformed token response: {payload!r}")

        return _Token(value=access_token, expires_at=self._now() + float(expires_in))


def _safe_body(response: httpx.Response) -> str:
    text = response.text or ""
    return text[:500]

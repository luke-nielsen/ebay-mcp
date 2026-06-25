"""Async HTTP client for the eBay Buy Browse API.

This is the only module that talks to the network. It owns an
:class:`httpx.AsyncClient`, attaches the OAuth token and marketplace headers,
translates friendly Python arguments into eBay's filter/sort grammar, retries
transient failures with exponential backoff, and returns typed
:class:`~ebay_mcp.models` objects.

Usage::

    async with EbayClient(Config.load()) as client:
        result = await client.search("nintendo switch oled", limit=50)
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .auth import TokenManager
from .config import Config
from .errors import EbayAPIError, EbayError
from .models import Item, SearchResult

# Map friendly sort keys to the Browse API's sort grammar.
_SORT_MAP = {
    "best_match": None,  # eBay's default relevance ranking; omit the parameter.
    "price_asc": "price",
    "price_desc": "-price",
    "newly_listed": "newlyListed",
    "ending_soonest": "endingSoonest",
}

# Map friendly condition keys to Browse API condition enum values.
_CONDITION_MAP = {
    "new": "NEW",
    "used": "USED",
    "certified_refurbished": "CERTIFIED_REFURBISHED",
    "seller_refurbished": "SELLER_REFURBISHED",
    "open_box": "NEW_OTHER",
}

# eBay caps a single Browse search page at 200 items.
MAX_PAGE_LIMIT = 200


class EbayClient:
    """A thin, typed async wrapper over the eBay Browse API."""

    def __init__(
        self,
        config: Config,
        *,
        http: httpx.AsyncClient | None = None,
        token_manager: TokenManager | None = None,
    ) -> None:
        self._config = config
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient()
        self._tokens = token_manager or TokenManager(config, self._http)

    async def __aenter__(self) -> EbayClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -- public API ---------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
        sort: str = "best_match",
        condition: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        buying_options: list[str] | None = None,
        category_ids: str | None = None,
        free_shipping_only: bool = False,
    ) -> SearchResult:
        """Search active listings via ``item_summary/search``."""

        if not query or not query.strip():
            raise EbayError("Search query must be a non-empty string.")
        if sort not in _SORT_MAP:
            raise EbayError(f"Unknown sort {sort!r}; expected one of {sorted(_SORT_MAP)}.")

        params: dict[str, Any] = {
            "q": query.strip(),
            "limit": max(1, min(int(limit), MAX_PAGE_LIMIT)),
            "offset": max(0, int(offset)),
        }
        sort_value = _SORT_MAP[sort]
        if sort_value:
            params["sort"] = sort_value
        if category_ids:
            params["category_ids"] = category_ids

        filters = self._build_filters(
            condition=condition,
            min_price=min_price,
            max_price=max_price,
            buying_options=buying_options,
            free_shipping_only=free_shipping_only,
        )
        if filters:
            params["filter"] = filters

        data = await self._get("/item_summary/search", params=params)
        return SearchResult.from_api(data)

    async def get_item(self, item_id: str) -> Item:
        """Fetch full details for a single item by its eBay item id."""

        if not item_id or not item_id.strip():
            raise EbayError("item_id must be a non-empty string.")
        data = await self._get(f"/item/{item_id.strip()}")
        return Item.from_api(data)

    # -- filter / header construction --------------------------------------

    def _build_filters(
        self,
        *,
        condition: str | None,
        min_price: float | None,
        max_price: float | None,
        buying_options: list[str] | None,
        free_shipping_only: bool,
    ) -> str:
        """Assemble eBay's comma-separated ``filter`` query value."""

        clauses: list[str] = []

        price_clause = _price_filter(min_price, max_price)
        if price_clause:
            clauses.append(price_clause)
            # priceCurrency is required by eBay whenever a price filter is set.
            clauses.append(f"priceCurrency:{_marketplace_currency(self._config.marketplace_id)}")

        if condition:
            mapped = _CONDITION_MAP.get(condition.lower())
            if not mapped:
                raise EbayError(
                    f"Unknown condition {condition!r}; expected one of {sorted(_CONDITION_MAP)}."
                )
            clauses.append(f"conditions:{{{mapped}}}")

        if buying_options:
            options = "|".join(opt.upper() for opt in buying_options)
            clauses.append(f"buyingOptions:{{{options}}}")

        if free_shipping_only:
            clauses.append("maxDeliveryCost:0")

        return ",".join(clauses)

    def _headers(self, token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": self._config.marketplace_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        ctx = _delivery_context(self._config)
        if ctx:
            headers["X-EBAY-C-ENDUSERCTX"] = ctx
        return headers

    # -- request plumbing ---------------------------------------------------

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._config.browse_base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(self._config.max_retries):
            token = await self._tokens.get_token(force_refresh=attempt > 0 and _was_auth(last_exc))
            try:
                response = await self._http.get(
                    url,
                    params=params,
                    headers=self._headers(token),
                    timeout=self._config.timeout,
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                await self._backoff(attempt)
                continue

            if response.status_code == 200:
                return response.json()

            # 401 once -> force a token refresh and retry; repeated 401 is fatal.
            if response.status_code == 401 and attempt + 1 < self._config.max_retries:
                last_exc = _api_error(response)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_exc = _api_error(response)
                if attempt + 1 < self._config.max_retries:
                    await self._backoff(attempt, retry_after=response.headers.get("Retry-After"))
                    continue

            raise _api_error(response)

        # Exhausted retries.
        if isinstance(last_exc, EbayError):
            raise last_exc
        raise EbayError(
            f"Request to {path} failed after {self._config.max_retries} attempts: {last_exc}"
        )

    async def _backoff(self, attempt: int, *, retry_after: str | None = None) -> None:
        if retry_after and retry_after.isdigit():
            delay = float(retry_after)
        else:
            delay = min(2.0**attempt, 8.0)
        await asyncio.sleep(delay)


def _was_auth(exc: Exception | None) -> bool:
    return isinstance(exc, EbayAPIError) and exc.status_code == 401


def _api_error(response: httpx.Response) -> EbayAPIError:
    """Build an :class:`EbayAPIError` from an error response body."""

    errors: list = []
    message = f"eBay API returned HTTP {response.status_code}"
    try:
        payload = response.json()
        errors = payload.get("errors") or []
        if errors and isinstance(errors, list):
            first = errors[0]
            message = first.get("message") or first.get("longMessage") or message
    except (ValueError, AttributeError):
        body = (response.text or "").strip()
        if body:
            message = f"{message}: {body[:300]}"
    return EbayAPIError(response.status_code, message, errors=errors)


def _price_filter(min_price: float | None, max_price: float | None) -> str | None:
    """Render a price range into eBay's ``price:[lo..hi]`` clause."""

    if min_price is None and max_price is None:
        return None
    lo = "" if min_price is None else f"{float(min_price):g}"
    hi = "" if max_price is None else f"{float(max_price):g}"
    return f"price:[{lo}..{hi}]"


# Default transactional currency per marketplace; used for the priceCurrency
# filter. Marketplaces not listed fall back to USD, which eBay tolerates for
# US-based searches.
_MARKETPLACE_CURRENCY = {
    "EBAY_US": "USD",
    "EBAY_GB": "GBP",
    "EBAY_DE": "EUR",
    "EBAY_FR": "EUR",
    "EBAY_IT": "EUR",
    "EBAY_ES": "EUR",
    "EBAY_AU": "AUD",
    "EBAY_CA": "CAD",
}


def _marketplace_currency(marketplace_id: str) -> str:
    return _MARKETPLACE_CURRENCY.get(marketplace_id, "USD")


def _delivery_context(config: Config) -> str | None:
    """Build the X-EBAY-C-ENDUSERCTX header for delivery-aware pricing."""

    parts = []
    if config.delivery_country:
        parts.append(f"contextualLocation=country%3D{config.delivery_country}")
        if config.delivery_postal_code:
            parts[-1] += f"%2Czip%3D{config.delivery_postal_code}"
    return ",".join(parts) if parts else None

"""MCP server exposing eBay marketplace data to Claude.

Tools return JSON-encoded strings: Claude receives a structured, self-describing
document it can parse and reason about. Network and configuration failures are
caught and returned as ``{"error": ...}`` payloads rather than raised, so a bad
query degrades into an explanation Claude can relay instead of an opaque tool
crash.

The ``mcp`` SDK and the :class:`~ebay_mcp.client.EbayClient` are created lazily
inside :func:`build_server` so the rest of the package imports cleanly without the
SDK installed or credentials configured (useful for tests and ``--help``). A
single :class:`EbayClient` is shared across tool calls -- and therefore one OAuth
token and one connection pool -- for the life of the server.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from . import analysis
from .client import EbayClient
from .config import Config, ConfigError
from .errors import EbayAPIError, EbayError

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP

# eBay caps a search page at 200; we sample up to this many for analysis tools.
_MAX_SAMPLE = 200


def _error_payload(exc: Exception) -> str:
    if isinstance(exc, EbayAPIError):
        return json.dumps(exc.to_dict(), indent=2)
    kind = "config_error" if isinstance(exc, ConfigError) else "ebay_error"
    return json.dumps({"error": kind, "message": str(exc)}, indent=2)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def build_server(config: Config | None = None, client: EbayClient | None = None) -> FastMCP:
    """Construct and return a configured :class:`FastMCP` server."""

    from mcp.server.fastmcp import FastMCP

    cfg = config or Config.load()

    # Lazily build (and cache) one shared client on first use so construction
    # happens on the server's running event loop.
    holder: dict[str, EbayClient] = {}
    if client is not None:
        holder["client"] = client

    def get_client() -> EbayClient:
        if "client" not in holder:
            holder["client"] = EbayClient(cfg)
        return holder["client"]

    mcp = FastMCP(
        "ebay",
        instructions=(
            "Tools for querying eBay's marketplace. Use `search_products` to find "
            "active listings, `analyze_prices` for a price distribution, "
            "`find_deals` for listings priced below the market median, "
            "`market_research` for a full overview (price spread, condition mix, "
            "shipping, seller signals), and `get_item_details` for one listing. "
            "All tools return JSON. Prices reflect total cost (item + shipping) "
            "unless noted, and are isolated to a single currency."
        ),
    )

    @mcp.tool()
    async def search_products(
        query: str,
        limit: int = 25,
        sort: str = "best_match",
        condition: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        free_shipping_only: bool = False,
    ) -> str:
        """Search active eBay listings.

        ``sort`` is one of ``best_match``, ``price_asc``, ``price_desc``,
        ``newly_listed``, ``ending_soonest``. ``condition`` is one of ``new``,
        ``used``, ``certified_refurbished``, ``seller_refurbished``, ``open_box``.
        Returns the matching listings plus eBay's total match count.
        """

        try:
            result = await get_client().search(
                query,
                limit=_clamp(limit, 1, _MAX_SAMPLE),
                sort=sort,
                condition=condition,
                min_price=min_price,
                max_price=max_price,
                free_shipping_only=free_shipping_only,
            )
        except (EbayError, ConfigError) as exc:
            return _error_payload(exc)
        return json.dumps(result.to_dict(), indent=2)

    @mcp.tool()
    async def analyze_prices(
        query: str,
        sample_size: int = 100,
        condition: str | None = None,
    ) -> str:
        """Analyse the price distribution for a search.

        Fetches a sample of active listings and returns count, min/max, mean,
        median, the 25th/75th/90th percentiles, and standard deviation -- all in a
        single currency and based on total cost (item + shipping).
        """

        try:
            result = await get_client().search(
                query,
                limit=_clamp(sample_size, 1, _MAX_SAMPLE),
                condition=condition,
            )
        except (EbayError, ConfigError) as exc:
            return _error_payload(exc)
        stats = analysis.price_statistics(result.items)
        return json.dumps(
            {"query": query, "total_matches": result.total, "price_statistics": stats},
            indent=2,
        )

    @mcp.tool()
    async def find_deals(
        query: str,
        sample_size: int = 100,
        threshold: float = 0.20,
        limit: int = 10,
        condition: str | None = None,
    ) -> str:
        """Find listings priced below the market median.

        Establishes a median total cost from a sample of listings and returns
        those at least ``threshold`` (default 0.20 = 20%) cheaper, ranked by
        discount.
        """

        try:
            result = await get_client().search(
                query,
                limit=_clamp(sample_size, 1, _MAX_SAMPLE),
                condition=condition,
            )
        except (EbayError, ConfigError) as exc:
            return _error_payload(exc)
        deals = analysis.find_deals(
            result.items,
            threshold=max(0.0, min(threshold, 0.95)),
            limit=_clamp(limit, 1, 50),
        )
        deals["query"] = query
        return json.dumps(deals, indent=2)

    @mcp.tool()
    async def market_research(
        query: str, sample_size: int = 100, condition: str | None = None
    ) -> str:
        """Produce a full market overview for a query.

        Combines price statistics, condition and buying-option breakdowns, price
        by condition, shipping mix, top seller locations, seller-feedback signal,
        and plain-language observations over a sample of active listings.
        """

        try:
            result = await get_client().search(
                query,
                limit=_clamp(sample_size, 1, _MAX_SAMPLE),
                condition=condition,
            )
        except (EbayError, ConfigError) as exc:
            return _error_payload(exc)
        report = analysis.market_research(result.items, query=query)
        report["total_matches"] = result.total
        return json.dumps(report, indent=2)

    @mcp.tool()
    async def get_item_details(item_id: str) -> str:
        """Fetch full details for a single listing by its eBay item id.

        Item ids look like ``v1|123456789|0`` and come from the other tools'
        ``item_id`` fields.
        """

        try:
            item = await get_client().get_item(item_id)
        except (EbayError, ConfigError) as exc:
            return _error_payload(exc)
        return json.dumps(item.to_dict(), indent=2)

    return mcp


def logging_setup() -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:  # pragma: no cover - exercised via the CLI / MCP host
    """Entry point that runs the server over stdio."""

    logging_setup()
    build_server().run()

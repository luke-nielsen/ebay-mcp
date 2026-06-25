"""ebay-mcp: serve eBay marketplace data to Claude over the Model Context Protocol.

The package is split into small, independently testable modules:

* :mod:`ebay_mcp.config`   -- runtime configuration loaded from the environment.
* :mod:`ebay_mcp.models`   -- value objects (:class:`Money`, :class:`Item`, ...).
* :mod:`ebay_mcp.auth`     -- OAuth2 client-credentials token management.
* :mod:`ebay_mcp.client`   -- the async eBay Browse API HTTP client.
* :mod:`ebay_mcp.analysis` -- pure price/market analysis functions.
* :mod:`ebay_mcp.server`   -- the MCP server exposing the analysis tools.

The networking layer (:mod:`auth`, :mod:`client`) is cleanly separated from the
pure analysis layer (:mod:`analysis`) so the latter can be unit-tested against
in-memory :class:`~ebay_mcp.models.Item` lists without touching the network.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .models import Item, Money, SearchResult, Seller

__all__ = ["Item", "Money", "SearchResult", "Seller", "__version__"]

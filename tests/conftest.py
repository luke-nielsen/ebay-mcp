"""Shared test fixtures and helpers."""

from __future__ import annotations

from typing import Any

import pytest

from ebay_mcp.config import Config
from ebay_mcp.models import Item


@pytest.fixture
def config() -> Config:
    """A fully-populated config that never touches the network."""

    return Config(
        client_id="test-client-id",
        client_secret="test-client-secret",
        environment="sandbox",
        marketplace_id="EBAY_US",
        max_retries=3,
    )


@pytest.fixture
def make_item():
    """Return a factory that builds an :class:`Item` from eBay-shaped JSON."""

    def _make(
        *,
        item_id: str = "v1|1|0",
        title: str = "Widget",
        price: float | None = 100.0,
        currency: str = "USD",
        condition: str = "New",
        shipping: float | None = 0.0,
        country: str = "US",
        buying_options: list[str] | None = None,
        feedback: float | None = 99.0,
    ) -> Item:
        data: dict[str, Any] = {
            "itemId": item_id,
            "title": title,
            "condition": condition,
            "buyingOptions": buying_options or ["FIXED_PRICE"],
            "itemLocation": {"country": country},
            "seller": {"username": "seller", "feedbackPercentage": feedback, "feedbackScore": 100},
        }
        if price is not None:
            data["price"] = {"value": str(price), "currency": currency}
        if shipping is not None:
            cost = {"value": str(shipping), "currency": currency}
            data["shippingOptions"] = [{"shippingCost": cost}]
        return Item.from_api(data)

    return _make

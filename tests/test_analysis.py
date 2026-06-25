"""Tests for the pure price/market analysis functions."""

from __future__ import annotations

from ebay_mcp import analysis


def test_price_statistics_empty():
    stats = analysis.price_statistics([])
    assert stats["count"] == 0
    assert stats["currency"] is None


def test_price_statistics_basic(make_item):
    items = [make_item(price=p, shipping=0.0) for p in (10, 20, 30, 40, 50)]
    stats = analysis.price_statistics(items)
    assert stats["count"] == 5
    assert stats["min"] == 10
    assert stats["max"] == 50
    assert stats["median"] == 30
    assert stats["mean"] == 30
    assert stats["p25"] == 20
    assert stats["p75"] == 40


def test_price_statistics_uses_total_cost_by_default(make_item):
    items = [make_item(price=100.0, shipping=10.0)]
    assert analysis.price_statistics(items)["min"] == 110.0
    assert analysis.price_statistics(items, use_total_cost=False)["min"] == 100.0


def test_extract_prices_isolates_dominant_currency(make_item):
    items = [
        make_item(price=10, currency="USD"),
        make_item(price=20, currency="USD"),
        make_item(price=999, currency="EUR"),
    ]
    prices, currency, excluded = analysis.extract_prices(items)
    assert currency == "USD"
    assert sorted(prices) == [10.0, 20.0]
    assert excluded == 1  # the lone EUR item


def test_find_deals_flags_below_median(make_item):
    # Sorted: 60, 90, 100, 100, 100, 110 -> median 100; the 60 item is 40% off.
    items = [make_item(price=p, shipping=0.0) for p in (90, 100, 100, 100, 110, 60)]
    result = analysis.find_deals(items, threshold=0.20)
    assert result["reference_median"] == 100
    assert result["deal_count"] == 1
    deal = result["deals"][0]
    assert deal["total_cost"] == 60
    assert deal["discount"] == 0.4


def test_find_deals_needs_enough_samples(make_item):
    result = analysis.find_deals([make_item(price=10), make_item(price=20)])
    assert result["deals"] == []
    assert "Not enough" in result["note"]


def test_find_deals_ranks_by_discount(make_item):
    items = [make_item(price=p) for p in (100, 100, 100, 100, 50, 70)]
    result = analysis.find_deals(items, threshold=0.10, limit=10)
    discounts = [d["discount"] for d in result["deals"]]
    assert discounts == sorted(discounts, reverse=True)
    assert result["deals"][0]["total_cost"] == 50


def test_market_research_empty():
    report = analysis.market_research([], query="nothing")
    assert report["sample_size"] == 0
    assert report["observations"]


def test_market_research_full(make_item):
    items = [
        make_item(price=100, condition="New", shipping=0.0, country="US"),
        make_item(price=120, condition="New", shipping=5.0, country="US"),
        make_item(price=70, condition="Used", shipping=0.0, country="GB"),
        make_item(price=80, condition="Used", shipping=0.0, country="US"),
    ]
    report = analysis.market_research(items, query="widget")
    assert report["sample_size"] == 4
    assert report["price_statistics"]["count"] == 4

    conditions = {c["name"]: c["count"] for c in report["condition_breakdown"]}
    assert conditions == {"New": 2, "Used": 2}

    assert "New" in report["price_by_condition"]
    assert report["price_by_condition"]["Used"]["count"] == 2

    assert report["shipping"]["free"] == 3
    assert report["shipping"]["paid"] == 1

    locations = {loc["name"]: loc["count"] for loc in report["top_seller_locations"]}
    assert locations["US"] == 3
    assert report["seller_feedback"]["samples"] == 4
    assert report["observations"]

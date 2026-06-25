"""Tests for the value-object parsing layer."""

from __future__ import annotations

from ebay_mcp.models import Item, Money, SearchResult, Seller


def test_money_parses_stringly_typed_values():
    money = Money.from_api({"value": "19.99", "currency": "USD"})
    assert money == Money(19.99, "USD")
    assert money.to_dict() == {"value": 19.99, "currency": "USD"}


def test_money_rejects_incomplete_data():
    assert Money.from_api(None) is None
    assert Money.from_api({"value": "5.00"}) is None  # missing currency
    assert Money.from_api({"currency": "USD"}) is None  # missing value
    assert Money.from_api({"value": "not-a-number", "currency": "USD"}) is None


def test_seller_parses_feedback():
    seller = Seller.from_api(
        {"username": "topshop", "feedbackPercentage": "98.7", "feedbackScore": 4200}
    )
    assert seller.username == "topshop"
    assert seller.feedback_percentage == 98.7
    assert seller.feedback_score == 4200


def test_item_total_cost_includes_shipping():
    item = Item.from_api(
        {
            "itemId": "v1|1|0",
            "title": "Camera",
            "price": {"value": "200.00", "currency": "USD"},
            "shippingOptions": [{"shippingCost": {"value": "12.50", "currency": "USD"}}],
        }
    )
    assert item.total_cost == 212.50
    assert item.free_shipping is False
    assert item.currency == "USD"


def test_item_free_shipping_detected():
    item = Item.from_api(
        {
            "itemId": "v1|2|0",
            "title": "Book",
            "price": {"value": "15.00", "currency": "USD"},
            "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "USD"}}],
        }
    )
    assert item.free_shipping is True
    assert item.total_cost == 15.00


def test_item_picks_cheapest_shipping_option():
    item = Item.from_api(
        {
            "itemId": "v1|3|0",
            "title": "Lamp",
            "price": {"value": "30.00", "currency": "USD"},
            "shippingOptions": [
                {"shippingCost": {"value": "9.99", "currency": "USD"}},
                {"shippingCost": {"value": "4.99", "currency": "USD"}},
            ],
        }
    )
    assert item.shipping_cost == Money(4.99, "USD")


def test_item_handles_missing_price_and_shipping():
    item = Item.from_api({"itemId": "v1|4|0", "title": "Mystery"})
    assert item.price is None
    assert item.total_cost is None
    assert item.shipping_cost is None
    assert item.free_shipping is False


def test_item_to_dict_is_json_shaped():
    item = Item.from_api(
        {
            "itemId": "v1|5|0",
            "title": "Phone",
            "price": {"value": "599.00", "currency": "USD"},
            "categories": [{"categoryId": "9355", "categoryName": "Cell Phones"}],
            "image": {"imageUrl": "http://img/x.jpg"},
        }
    )
    out = item.to_dict()
    assert out["title"] == "Phone"
    assert out["price"] == {"value": 599.0, "currency": "USD"}
    assert out["categories"] == ["Cell Phones"]
    assert out["image_url"] == "http://img/x.jpg"


def test_search_result_parsing():
    result = SearchResult.from_api(
        {
            "total": 1234,
            "limit": 2,
            "offset": 0,
            "itemSummaries": [
                {"itemId": "v1|1|0", "title": "A", "price": {"value": "1", "currency": "USD"}},
                {"itemId": "v1|2|0", "title": "B", "price": {"value": "2", "currency": "USD"}},
            ],
        }
    )
    assert result.total == 1234
    assert len(result.items) == 2
    assert result.to_dict()["returned"] == 2

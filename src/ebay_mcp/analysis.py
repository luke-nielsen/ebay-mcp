"""Pure price- and market-analysis functions over collections of :class:`Item`.

Everything here is side-effect free and operates on in-memory item lists, so it
can be unit-tested without any network access. The MCP server is responsible for
fetching items via :class:`~ebay_mcp.client.EbayClient` and handing them here.

A note on money: a single search can mix currencies (e.g. international sellers
on EBAY_US). Rather than silently averaging USD with EUR, :func:`extract_prices`
isolates the dominant currency and reports how many items were excluded, so every
statistic carries a single, unambiguous currency.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence

from .models import Item


def _percentile(sorted_values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (``q`` in ``[0, 100]``) over sorted data."""

    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (q / 100.0) * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(sorted_values[low])
    frac = rank - low
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac)


def extract_prices(
    items: Sequence[Item], *, use_total_cost: bool = True
) -> tuple[list[float], str | None, int]:
    """Return ``(prices, currency, excluded)`` for the dominant currency.

    ``prices`` are the values (total cost incl. shipping by default, otherwise the
    listed item price) for every item in the most common currency. ``excluded`` is
    the number of items dropped because they used a different currency or lacked a
    price.
    """

    by_currency: dict[str, list[float]] = {}
    no_price = 0
    for item in items:
        if item.price is None:
            no_price += 1
            continue
        value = item.total_cost if use_total_cost else item.price.value
        if value is None:
            no_price += 1
            continue
        by_currency.setdefault(item.price.currency, []).append(value)

    if not by_currency:
        return [], None, no_price

    currency = max(by_currency, key=lambda c: len(by_currency[c]))
    prices = by_currency[currency]
    excluded = no_price + sum(len(v) for c, v in by_currency.items() if c != currency)
    return prices, currency, excluded


def price_statistics(items: Sequence[Item], *, use_total_cost: bool = True) -> dict[str, object]:
    """Compute a price distribution summary for ``items``."""

    prices, currency, excluded = extract_prices(items, use_total_cost=use_total_cost)
    if not prices:
        return {
            "count": 0,
            "currency": currency,
            "excluded": excluded,
            "basis": "total_cost" if use_total_cost else "item_price",
        }

    ordered = sorted(prices)
    return {
        "count": len(ordered),
        "currency": currency,
        "excluded": excluded,
        "basis": "total_cost" if use_total_cost else "item_price",
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
        "mean": round(statistics.fmean(ordered), 2),
        "median": round(statistics.median(ordered), 2),
        "p25": round(_percentile(ordered, 25), 2),
        "p75": round(_percentile(ordered, 75), 2),
        "p90": round(_percentile(ordered, 90), 2),
        "stdev": round(statistics.pstdev(ordered), 2) if len(ordered) > 1 else 0.0,
    }


def find_deals(
    items: Sequence[Item],
    *,
    threshold: float = 0.20,
    limit: int = 10,
) -> dict[str, object]:
    """Surface listings priced meaningfully below the market median.

    A "deal" is an item whose total cost is at least ``threshold`` (default 20%)
    below the median total cost of all same-currency items. Each deal carries a
    ``discount`` fraction so Claude can rank and explain them.
    """

    prices, currency, excluded = extract_prices(items, use_total_cost=True)
    if len(prices) < 3:
        return {
            "deals": [],
            "currency": currency,
            "reference_median": None,
            "note": "Not enough comparable listings to establish a market median.",
        }

    median = statistics.median(prices)
    cutoff = median * (1.0 - threshold)

    deals = []
    for item in items:
        if item.price is None or item.price.currency != currency:
            continue
        total = item.total_cost
        if total is None or total > cutoff or median <= 0:
            continue
        deals.append(
            {
                "discount": round((median - total) / median, 4),
                "total_cost": total,
                "item": item.to_dict(),
            }
        )

    deals.sort(key=lambda d: d["discount"], reverse=True)
    return {
        "currency": currency,
        "reference_median": round(median, 2),
        "threshold": threshold,
        "excluded": excluded,
        "deal_count": len(deals),
        "deals": deals[:limit],
    }


def _counter_to_list(counter: Counter[str], n: int | None = None) -> list[dict[str, object]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(n)]


def market_research(items: Sequence[Item], *, query: str | None = None) -> dict[str, object]:
    """Build a comprehensive market overview for a set of listings."""

    if not items:
        return {
            "query": query,
            "sample_size": 0,
            "price_statistics": price_statistics(items),
            "observations": ["No listings were returned for this query."],
        }

    price_stats = price_statistics(items, use_total_cost=True)
    item_price_stats = price_statistics(items, use_total_cost=False)

    condition_counts: Counter[str] = Counter(i.condition or "Unspecified" for i in items)
    buying_counts: Counter[str] = Counter(opt for i in items for opt in i.buying_options)
    location_counts: Counter[str] = Counter(
        i.item_location_country for i in items if i.item_location_country
    )

    free = sum(1 for i in items if i.free_shipping)
    paid = sum(1 for i in items if i.shipping_cost and i.shipping_cost.value > 0)
    unknown = len(items) - free - paid

    # Per-condition price medians, where there are enough samples to be meaningful.
    price_by_condition: dict[str, object] = {}
    for cond in condition_counts:
        subset = [i for i in items if (i.condition or "Unspecified") == cond]
        stats = price_statistics(subset, use_total_cost=True)
        if stats["count"]:
            price_by_condition[cond] = {
                "count": stats["count"],
                "median": stats.get("median"),
                "min": stats.get("min"),
                "max": stats.get("max"),
            }

    feedbacks = [
        i.seller.feedback_percentage
        for i in items
        if i.seller and i.seller.feedback_percentage is not None
    ]

    report: dict[str, object] = {
        "query": query,
        "sample_size": len(items),
        "price_statistics": price_stats,
        "item_price_statistics": item_price_stats,
        "condition_breakdown": _counter_to_list(condition_counts),
        "price_by_condition": price_by_condition,
        "buying_options": _counter_to_list(buying_counts),
        "top_seller_locations": _counter_to_list(location_counts, 10),
        "shipping": {
            "free": free,
            "paid": paid,
            "unknown": unknown,
        },
        "seller_feedback": {
            "samples": len(feedbacks),
            "mean_percentage": round(statistics.fmean(feedbacks), 2) if feedbacks else None,
        },
        "observations": _observations(items, price_stats, condition_counts, free),
    }
    return report


def _observations(
    items: Sequence[Item],
    price_stats: dict[str, object],
    conditions: Counter[str],
    free_shipping: int,
) -> list[str]:
    """Plain-language takeaways so Claude can summarise without re-deriving them."""

    notes: list[str] = []
    count = price_stats.get("count", 0)
    if not count:
        return ["No comparable prices were available for this query."]

    currency = price_stats.get("currency")
    notes.append(
        f"{count} comparable listings priced from {price_stats['min']} to "
        f"{price_stats['max']} {currency} (median {price_stats['median']})."
    )

    spread = price_stats.get("p75", 0) - price_stats.get("p25", 0)
    median = price_stats.get("median") or 0
    if median and spread / median > 0.6:
        notes.append(
            "Wide price spread between the 25th and 75th percentiles -- condition, "
            "bundling, or seller reputation likely drive the variance."
        )

    top_condition, top_count = conditions.most_common(1)[0]
    notes.append(
        f"Most common condition is {top_condition} "
        f"({top_count} of {len(items)} listings)."
    )

    if free_shipping:
        notes.append(f"{free_shipping} of {len(items)} listings offer free shipping.")

    return notes

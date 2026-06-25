# ebay-mcp

Expose eBay's marketplace to Claude over the
[Model Context Protocol](https://modelcontextprotocol.io). Claude can search
active listings, analyse price distributions, surface deals priced below the
market median, and produce a market-research overview — all as structured JSON it
can reason about.

It answers questions like:

- *What does a used Nintendo Switch OLED actually sell for right now?*
- *Find me listings priced well below the going rate.*
- *Give me a market overview: price spread, condition mix, who's selling, and shipping.*

## How it works

```
                       OAuth2 (client credentials)
                              │
 ┌────────┐   tools    ┌──────┴───────┐   HTTPS   ┌──────────────────┐
 │ Claude │ ────────►  │  ebay-mcp    │ ────────► │ eBay Buy Browse  │
 │        │ ◄────────  │  MCP server  │ ◄──────── │ API              │
 └────────┘    JSON    └──────────────┘           └──────────────────┘
```

The server authenticates to eBay with the OAuth2 *client-credentials* grant
(caching and refreshing the application token), calls the **Buy Browse API**,
normalises the verbose responses into typed objects, and runs price/market
analysis locally before handing JSON back to Claude.

The code is layered so the analysis is testable without the network:

- `config.py` — environment-driven configuration.
- `models.py` — typed value objects parsed from eBay JSON.
- `auth.py` — OAuth token caching/refresh (concurrency-safe).
- `client.py` — the only module that talks to eBay; retries + filter grammar.
- `analysis.py` — pure price/deal/market functions.
- `server.py` — the MCP tools.

## Tools

| Tool | What it does |
| --- | --- |
| `search_products` | Search active listings (sort, condition, price range, free-shipping filters). |
| `analyze_prices` | Price distribution for a query: min/max, mean, median, p25/p75/p90, stdev. |
| `find_deals` | Listings priced at least *N%* below the market median, ranked by discount. |
| `market_research` | Full overview: price stats, condition mix, price-by-condition, shipping, seller locations, observations. |
| `get_item_details` | Full details for a single listing by item id. |

All prices are isolated to a single currency and, unless noted, reflect total
cost (item + shipping).

## Setup

Requires Python 3.10+ and an eBay developer account.

1. Create an application at <https://developer.ebay.com/my/keys> and copy the
   **App ID (Client ID)** and **Cert ID (Client Secret)**.
2. Install:

   ```bash
   git clone https://github.com/luke-nielsen/ebay-mcp.git
   cd ebay-mcp
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. Configure credentials (copy `.env.example` to `.env`, or export directly):

   ```bash
   export EBAY_CLIENT_ID=your-app-id
   export EBAY_CLIENT_SECRET=your-cert-id
   ```

4. Verify connectivity:

   ```bash
   ebay-mcp check
   ebay-mcp search "nintendo switch oled" --limit 5
   ebay-mcp research "airpods pro 2"
   ```

## Connecting to Claude

Add the server to your MCP host. For Claude Code:

```bash
claude mcp add ebay -- ebay-mcp serve
```

Or use the bundled `.mcp.json` (it reads `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`
from your environment). The server speaks MCP over stdio.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `EBAY_CLIENT_ID` | — | App ID (Client ID). **Required.** |
| `EBAY_CLIENT_SECRET` | — | Cert ID (Client Secret). **Required.** |
| `EBAY_ENVIRONMENT` | `production` | `production` or `sandbox`. |
| `EBAY_MARKETPLACE_ID` | `EBAY_US` | e.g. `EBAY_GB`, `EBAY_DE`, `EBAY_AU`. |
| `EBAY_DELIVERY_COUNTRY` | — | Buyer country for shipping estimates. |
| `EBAY_DELIVERY_POSTAL_CODE` | — | Buyer postal code for shipping estimates. |
| `EBAY_TIMEOUT` | `20` | Per-request timeout (seconds). |
| `EBAY_MAX_RETRIES` | `3` | Retry attempts for transient failures. |

## Development

```bash
pip install -e ".[dev]"
pytest        # run the test suite
ruff check .  # lint
```

The networking layer is exercised with `httpx.MockTransport`, so the full suite
runs offline and needs no credentials.

## Notes & limitations

- Uses the **Buy Browse API**, which covers *active* listings. Sold/completed
  price history requires eBay's restricted Marketplace Insights API and is out of
  scope here; "market" statistics are therefore over current asking prices.
- The client-credentials token grants access to public search only — no
  user-specific or order data.
- eBay rate limits the Browse API (default ~5,000 calls/day); the analysis tools
  spend one call each.

## License

MIT — see [LICENSE](LICENSE).

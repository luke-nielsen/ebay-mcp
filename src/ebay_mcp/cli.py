"""Command-line interface.

Subcommands:

* ``serve``  -- run the MCP server over stdio (for a Claude/MCP host).
* ``search`` -- run a one-off product search and print JSON (handy smoke test).
* ``research`` -- print a market overview for a query.
* ``check`` -- verify credentials by requesting an OAuth token.

``search``, ``research``, and ``check`` exist so the eBay integration can be
exercised from a terminal without wiring up an MCP host -- the fastest way to
confirm credentials and connectivity.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from . import __version__, analysis
from .client import EbayClient
from .config import Config, ConfigError
from .errors import EbayError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ebay-mcp",
        description="Serve eBay marketplace data to Claude over the Model Context Protocol.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the MCP server over stdio")
    p_serve.set_defaults(func=_cmd_serve)

    p_search = sub.add_parser("search", help="run a one-off product search")
    p_search.add_argument("query", help="search keywords")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument(
        "--sort",
        default="best_match",
        choices=["best_match", "price_asc", "price_desc", "newly_listed", "ending_soonest"],
    )
    p_search.add_argument("--condition", default=None)
    p_search.add_argument("--min-price", type=float, default=None)
    p_search.add_argument("--max-price", type=float, default=None)
    p_search.set_defaults(func=_cmd_search)

    p_research = sub.add_parser("research", help="print a market overview for a query")
    p_research.add_argument("query", help="search keywords")
    p_research.add_argument("--sample-size", type=int, default=100)
    p_research.add_argument("--condition", default=None)
    p_research.set_defaults(func=_cmd_research)

    p_check = sub.add_parser("check", help="verify credentials by requesting a token")
    p_check.set_defaults(func=_cmd_check)

    return parser


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import build_server, logging_setup

    logging_setup()
    build_server(Config.load()).run()
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    async def run() -> int:
        async with EbayClient(Config.load()) as client:
            result = await client.search(
                args.query,
                limit=args.limit,
                sort=args.sort,
                condition=args.condition,
                min_price=args.min_price,
                max_price=args.max_price,
            )
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    return _run(run())


def _cmd_research(args: argparse.Namespace) -> int:
    async def run() -> int:
        async with EbayClient(Config.load()) as client:
            result = await client.search(
                args.query, limit=args.sample_size, condition=args.condition
            )
        report = analysis.market_research(result.items, query=args.query)
        report["total_matches"] = result.total
        print(json.dumps(report, indent=2))
        return 0

    return _run(run())


def _cmd_check(args: argparse.Namespace) -> int:
    import httpx

    from .auth import TokenManager

    async def run() -> int:
        config = Config.load()
        config.require_credentials()
        async with httpx.AsyncClient() as http:
            token = await TokenManager(config, http).get_token()
        print(
            json.dumps(
                {
                    "ok": True,
                    "environment": config.environment,
                    "marketplace_id": config.marketplace_id,
                    "token_prefix": token[:12] + "...",
                },
                indent=2,
            )
        )
        return 0

    return _run(run())


def _run(coro) -> int:
    try:
        return asyncio.run(coro)
    except (EbayError, ConfigError) as exc:
        payload = json.dumps({"error": type(exc).__name__, "message": str(exc)}, indent=2)
        print(payload, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

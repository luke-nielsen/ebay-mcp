"""Allow ``python -m ebay_mcp`` to behave like the console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

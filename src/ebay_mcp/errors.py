"""Exception hierarchy for the eBay client.

A single base (:class:`EbayError`) lets the MCP tools catch every expected
failure mode and turn it into a structured JSON error for Claude, while leaving
genuinely unexpected exceptions to propagate.
"""

from __future__ import annotations


class EbayError(Exception):
    """Base class for all expected eBay client failures."""


class EbayAuthError(EbayError):
    """OAuth token acquisition failed (bad credentials, network, malformed reply)."""


class EbayAPIError(EbayError):
    """The Browse API returned an error response."""

    def __init__(self, status_code: int, message: str, *, errors: list | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []

    def to_dict(self) -> dict[str, object]:
        return {
            "error": "ebay_api_error",
            "status_code": self.status_code,
            "message": str(self),
            "details": self.errors,
        }

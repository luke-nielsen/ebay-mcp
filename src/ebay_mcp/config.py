"""Runtime configuration.

All settings are resolved from environment variables so the server can be wired
into a Claude/MCP host without any code changes. The only required values are the
eBay application credentials (``EBAY_CLIENT_ID`` / ``EBAY_CLIENT_SECRET``), which
are issued from the eBay developer portal as the "App ID" and "Cert ID".

Two eBay environments are supported. ``production`` talks to real listings;
``sandbox`` talks to eBay's test marketplace (which returns synthetic data). The
correct base URLs and OAuth endpoints are derived from the choice so callers only
ever set ``EBAY_ENVIRONMENT``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Default OAuth scope for the Buy Browse API under client-credentials grant.
DEFAULT_SCOPE = "https://api.ebay.com/oauth/api_scope"

_HOSTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}


class ConfigError(RuntimeError):
    """Raised when the configuration is missing values required to make a call."""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Resolved configuration for the eBay client and MCP server."""

    client_id: str
    client_secret: str
    environment: str = "production"
    marketplace_id: str = "EBAY_US"
    scopes: tuple[str, ...] = (DEFAULT_SCOPE,)
    # Network behaviour.
    timeout: float = 20.0
    max_retries: int = 3
    # How long before a token's stated expiry we proactively refresh it.
    token_leeway: float = 60.0
    # Optional ISO 3166-1 alpha-2 country and postal code used to estimate
    # delivery for the calling buyer (improves shipping cost accuracy).
    delivery_country: str | None = None
    delivery_postal_code: str | None = None
    _extra: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def load(cls) -> Config:
        """Build a :class:`Config` from the environment.

        Missing credentials are tolerated here so the package can be imported and
        partially exercised (e.g. ``--help``) without them; the credentials are
        validated lazily by :meth:`require_credentials` before any network call.
        """

        environment = os.environ.get("EBAY_ENVIRONMENT", "production").strip().lower()
        if environment not in _HOSTS:
            raise ConfigError(
                f"EBAY_ENVIRONMENT must be one of {sorted(_HOSTS)}, got {environment!r}"
            )

        scope_raw = os.environ.get("EBAY_OAUTH_SCOPES")
        scopes = tuple(scope_raw.split()) if scope_raw else (DEFAULT_SCOPE,)

        return cls(
            client_id=os.environ.get("EBAY_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("EBAY_CLIENT_SECRET", "").strip(),
            environment=environment,
            marketplace_id=os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US").strip(),
            scopes=scopes,
            timeout=_env_float("EBAY_TIMEOUT", 20.0),
            max_retries=_env_int("EBAY_MAX_RETRIES", 3),
            token_leeway=_env_float("EBAY_TOKEN_LEEWAY", 60.0),
            delivery_country=os.environ.get("EBAY_DELIVERY_COUNTRY") or None,
            delivery_postal_code=os.environ.get("EBAY_DELIVERY_POSTAL_CODE") or None,
        )

    @property
    def host(self) -> str:
        """Base API host for the configured environment."""

        return _HOSTS[self.environment]

    @property
    def oauth_token_url(self) -> str:
        return f"{self.host}/identity/v1/oauth2/token"

    @property
    def browse_base_url(self) -> str:
        return f"{self.host}/buy/browse/v1"

    def require_credentials(self) -> None:
        """Validate that credentials are present, raising :class:`ConfigError` if not."""

        missing = [
            name
            for name, value in (
                ("EBAY_CLIENT_ID", self.client_id),
                ("EBAY_CLIENT_SECRET", self.client_secret),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                "Missing eBay credentials: "
                + ", ".join(missing)
                + ". Create an application at https://developer.ebay.com and set the "
                "App ID and Cert ID as these environment variables."
            )

"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest

from ebay_mcp.config import Config, ConfigError


def test_load_defaults(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("EBAY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")

    config = Config.load()
    assert config.environment == "production"
    assert config.marketplace_id == "EBAY_US"
    assert config.host == "https://api.ebay.com"
    assert config.oauth_token_url.endswith("/identity/v1/oauth2/token")
    assert config.browse_base_url.endswith("/buy/browse/v1")


def test_sandbox_environment(monkeypatch):
    monkeypatch.setenv("EBAY_ENVIRONMENT", "sandbox")
    config = Config.load()
    assert config.host == "https://api.sandbox.ebay.com"


def test_invalid_environment_raises(monkeypatch):
    monkeypatch.setenv("EBAY_ENVIRONMENT", "staging")
    with pytest.raises(ConfigError):
        Config.load()


def test_require_credentials():
    incomplete = Config(client_id="", client_secret="")
    with pytest.raises(ConfigError) as info:
        incomplete.require_credentials()
    assert "EBAY_CLIENT_ID" in str(info.value)
    assert "EBAY_CLIENT_SECRET" in str(info.value)

    Config(client_id="a", client_secret="b").require_credentials()  # no raise

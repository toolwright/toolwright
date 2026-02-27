"""Tests for the OAuth credential provider.

Tests OAuthCredentialProvider which manages OAuth2 client-credentials
tokens with automatic refresh, per-host configuration, and graceful
fallback when authlib is not installed.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolwright.core.auth.oauth import (
    OAuthConfig,
    OAuthCredentialProvider,
    OAuthError,
)


# ---------------------------------------------------------------------------
# OAuthConfig model
# ---------------------------------------------------------------------------


class TestOAuthConfig:
    """OAuthConfig captures OAuth2 client-credentials settings."""

    def test_basic_config(self):
        cfg = OAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="my-client",
            client_secret="my-secret",
        )
        assert cfg.token_url == "https://auth.example.com/token"
        assert cfg.client_id == "my-client"
        assert cfg.client_secret == "my-secret"
        assert cfg.scopes == []

    def test_config_with_scopes(self):
        cfg = OAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="c",
            client_secret="s",
            scopes=["read", "write"],
        )
        assert cfg.scopes == ["read", "write"]

    def test_serialization(self):
        cfg = OAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="c",
            client_secret="s",
        )
        d = cfg.model_dump()
        assert "token_url" in d
        assert "client_id" in d


# ---------------------------------------------------------------------------
# OAuthCredentialProvider
# ---------------------------------------------------------------------------


class TestConfigure:
    """configure() registers OAuth config per host."""

    def test_configure_host(self):
        provider = OAuthCredentialProvider()
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )
        assert "api.example.com" in provider._configs

    def test_configure_replaces_existing(self):
        provider = OAuthCredentialProvider()
        cfg1 = OAuthConfig(token_url="https://a/token", client_id="c1", client_secret="s1")
        cfg2 = OAuthConfig(token_url="https://b/token", client_id="c2", client_secret="s2")
        provider.configure("host", cfg1)
        provider.configure("host", cfg2)
        assert provider._configs["host"].client_id == "c2"


class TestGetToken:
    """get_token() returns a valid token, fetching/refreshing as needed."""

    @pytest.mark.asyncio
    async def test_get_token_unconfigured_host(self):
        """Should raise OAuthError for unconfigured host."""
        provider = OAuthCredentialProvider()
        with pytest.raises(OAuthError, match="not configured"):
            await provider.get_token("unknown.host.com")

    @pytest.mark.asyncio
    async def test_get_token_fetches_on_first_call(self):
        """First call should fetch a new token."""
        provider = OAuthCredentialProvider()
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )
        with patch.object(
            provider, "_fetch_token", return_value=("access-token-123", 3600)
        ):
            token = await provider.get_token("api.example.com")
        assert token == "access-token-123"

    @pytest.mark.asyncio
    async def test_get_token_returns_cached(self):
        """Subsequent calls should return cached token without re-fetching."""
        provider = OAuthCredentialProvider()
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )
        fetch_mock = AsyncMock(return_value=("cached-token", 3600))
        provider._fetch_token = fetch_mock

        token1 = await provider.get_token("api.example.com")
        token2 = await provider.get_token("api.example.com")

        assert token1 == token2 == "cached-token"
        assert fetch_mock.call_count == 1  # Only fetched once

    @pytest.mark.asyncio
    async def test_get_token_refreshes_expired(self):
        """Should re-fetch when token has expired."""
        provider = OAuthCredentialProvider()
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )

        # Store an already-expired token
        provider._tokens["api.example.com"] = ("old-token", time.time() - 10)

        with patch.object(
            provider, "_fetch_token", return_value=("new-token", 3600)
        ):
            token = await provider.get_token("api.example.com")

        assert token == "new-token"


class TestRefreshToken:
    """refresh_token() forces a token refresh."""

    @pytest.mark.asyncio
    async def test_refresh_unconfigured(self):
        provider = OAuthCredentialProvider()
        with pytest.raises(OAuthError, match="not configured"):
            await provider.refresh_token("unknown.host.com")

    @pytest.mark.asyncio
    async def test_refresh_forces_new_fetch(self):
        provider = OAuthCredentialProvider()
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )
        # Pre-cache a valid token
        provider._tokens["api.example.com"] = ("old-token", time.time() + 9999)

        with patch.object(
            provider, "_fetch_token", return_value=("refreshed-token", 3600)
        ):
            token = await provider.refresh_token("api.example.com")

        assert token == "refreshed-token"


class TestTokenExpiry:
    """Token expiry margin ensures proactive refresh."""

    @pytest.mark.asyncio
    async def test_token_near_expiry_refreshes(self):
        """Token within expiry_margin should be refreshed."""
        provider = OAuthCredentialProvider(expiry_margin_seconds=60)
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )
        # Token expires in 30s, within 60s margin
        provider._tokens["api.example.com"] = ("expiring-token", time.time() + 30)

        with patch.object(
            provider, "_fetch_token", return_value=("fresh-token", 3600)
        ):
            token = await provider.get_token("api.example.com")

        assert token == "fresh-token"

    @pytest.mark.asyncio
    async def test_token_well_within_validity(self):
        """Token far from expiry should be returned as-is."""
        provider = OAuthCredentialProvider(expiry_margin_seconds=60)
        provider.configure(
            "api.example.com",
            OAuthConfig(
                token_url="https://auth.example.com/token",
                client_id="c",
                client_secret="s",
            ),
        )
        # Token expires in 1 hour, well beyond margin
        provider._tokens["api.example.com"] = ("valid-token", time.time() + 3600)

        token = await provider.get_token("api.example.com")
        assert token == "valid-token"


class TestClearTokens:
    """clear_tokens() removes cached tokens."""

    def test_clear_specific_host(self):
        provider = OAuthCredentialProvider()
        provider._tokens["a.com"] = ("t1", time.time() + 3600)
        provider._tokens["b.com"] = ("t2", time.time() + 3600)
        provider.clear_tokens("a.com")
        assert "a.com" not in provider._tokens
        assert "b.com" in provider._tokens

    def test_clear_all(self):
        provider = OAuthCredentialProvider()
        provider._tokens["a.com"] = ("t1", time.time() + 3600)
        provider._tokens["b.com"] = ("t2", time.time() + 3600)
        provider.clear_tokens()
        assert len(provider._tokens) == 0


class TestConfiguredHosts:
    """configured_hosts() lists hosts with OAuth config."""

    def test_empty(self):
        provider = OAuthCredentialProvider()
        assert provider.configured_hosts() == []

    def test_lists_hosts(self):
        provider = OAuthCredentialProvider()
        provider.configure("a.com", OAuthConfig(token_url="t", client_id="c", client_secret="s"))
        provider.configure("b.com", OAuthConfig(token_url="t", client_id="c", client_secret="s"))
        hosts = provider.configured_hosts()
        assert set(hosts) == {"a.com", "b.com"}

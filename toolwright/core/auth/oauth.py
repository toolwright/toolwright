"""OAuth2 client-credentials provider.

Manages per-host OAuth2 tokens with automatic refresh and
proactive expiry margin. Uses ``httpx`` for token endpoint requests.

Install the optional dependency for authlib-based flows:
    pip install "toolwright[oauth]"
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OAuthError(Exception):
    """Raised for OAuth configuration or token errors."""


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


class OAuthConfig(BaseModel):
    """OAuth2 client-credentials configuration for a single host."""

    token_url: str
    client_id: str
    client_secret: str
    scopes: list[str] = Field(default_factory=list)
    extra_params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Credential provider
# ---------------------------------------------------------------------------


class OAuthCredentialProvider:
    """Per-host OAuth2 token manager with automatic refresh.

    Tokens are cached in memory and refreshed proactively when they
    fall within ``expiry_margin_seconds`` of expiration.
    """

    def __init__(self, *, expiry_margin_seconds: float = 30.0) -> None:
        self.expiry_margin_seconds = expiry_margin_seconds
        # host -> OAuthConfig
        self._configs: dict[str, OAuthConfig] = {}
        # host -> (access_token, expires_at_timestamp)
        self._tokens: dict[str, tuple[str, float]] = {}

    # -- Configuration -----------------------------------------------------

    def configure(self, host: str, config: OAuthConfig) -> None:
        """Register OAuth config for a host."""
        self._configs[host] = config
        # Clear any cached token when config changes
        self._tokens.pop(host, None)

    def configured_hosts(self) -> list[str]:
        """Return list of hosts with OAuth config."""
        return list(self._configs.keys())

    # -- Token lifecycle ---------------------------------------------------

    async def get_token(self, host: str) -> str:
        """Get a valid access token for *host*.

        Returns a cached token if still valid (beyond expiry margin),
        otherwise fetches a new one.

        Raises:
            OAuthError: If the host is not configured or fetch fails.
        """
        if host not in self._configs:
            raise OAuthError(f"OAuth not configured for host: {host}")

        # Check cache
        if host in self._tokens:
            token, expires_at = self._tokens[host]
            if time.time() + self.expiry_margin_seconds < expires_at:
                return token

        # Fetch new token
        return await self._do_fetch(host)

    async def refresh_token(self, host: str) -> str:
        """Force-refresh the token for *host*.

        Raises:
            OAuthError: If the host is not configured or fetch fails.
        """
        if host not in self._configs:
            raise OAuthError(f"OAuth not configured for host: {host}")

        return await self._do_fetch(host)

    def clear_tokens(self, host: str | None = None) -> None:
        """Clear cached tokens.

        Args:
            host: If given, clear only this host. Otherwise clear all.
        """
        if host is not None:
            self._tokens.pop(host, None)
        else:
            self._tokens.clear()

    # -- Internal ----------------------------------------------------------

    async def _do_fetch(self, host: str) -> str:
        """Fetch and cache a new token."""
        token, expires_in = await self._fetch_token(host)
        expires_at = time.time() + expires_in
        self._tokens[host] = (token, expires_at)
        return token

    async def _fetch_token(self, host: str) -> tuple[str, int]:
        """Fetch an access token from the token endpoint.

        Returns (access_token, expires_in_seconds).
        """
        config = self._configs[host]

        try:
            import httpx
        except ImportError:
            raise OAuthError(
                "httpx is required for OAuth token fetching. "
                "Install with: pip install httpx"
            ) from None

        async with httpx.AsyncClient(timeout=30.0) as client:
            data: dict[str, Any] = {
                "grant_type": "client_credentials",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
            }
            if config.scopes:
                data["scope"] = " ".join(config.scopes)
            data.update(config.extra_params)

            try:
                response = await client.post(config.token_url, data=data)
                response.raise_for_status()
            except Exception as exc:
                raise OAuthError(
                    f"Token fetch failed for {host}: {exc}"
                ) from exc

            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise OAuthError(
                    f"No access_token in response from {config.token_url}"
                )

            expires_in = int(payload.get("expires_in", 3600))
            return (access_token, expires_in)

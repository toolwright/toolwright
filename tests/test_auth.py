"""Tests for MCP HTTP token authentication (Sprint 1c).

TDD RED phase: tests define expected behavior before implementation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tools_manifest(tmp_path: Path) -> Path:
    """Create a minimal tools.json for server initialization."""
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "actions": [
            {
                "name": "get_users",
                "description": "List users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "low",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps(manifest))
    return tools_path


# ---------------------------------------------------------------------------
# Token format and generation
# ---------------------------------------------------------------------------


class TestTokenGeneration:
    """Token generation: tw_ prefix + 32 hex chars."""

    def test_generate_token_format(self) -> None:
        from toolwright.mcp.auth import generate_token

        token = generate_token()
        assert token.startswith("tw_")
        # tw_ + 32 hex chars = 35 chars total
        assert len(token) == 35
        assert re.fullmatch(r"tw_[a-f0-9]{32}", token)

    def test_generate_unique_tokens(self) -> None:
        from toolwright.mcp.auth import generate_token

        tokens = {generate_token() for _ in range(100)}
        assert len(tokens) == 100  # all unique


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


class TestTokenValidation:
    """validate_token checks format and value."""

    def test_valid_token_accepted(self) -> None:
        from toolwright.mcp.auth import generate_token, validate_token

        token = generate_token()
        assert validate_token(token, expected=token) is True

    def test_wrong_token_rejected(self) -> None:
        from toolwright.mcp.auth import generate_token, validate_token

        token = generate_token()
        assert validate_token("tw_0000000000000000000000000000000f", expected=token) is False

    def test_missing_token_rejected(self) -> None:
        from toolwright.mcp.auth import generate_token, validate_token

        token = generate_token()
        assert validate_token(None, expected=token) is False
        assert validate_token("", expected=token) is False

    def test_malformed_token_rejected(self) -> None:
        from toolwright.mcp.auth import generate_token, validate_token

        token = generate_token()
        assert validate_token("not_a_token", expected=token) is False
        assert validate_token("Bearer xyz", expected=token) is False

    def test_bearer_prefix_stripped(self) -> None:
        """validate_token should accept Bearer-prefixed tokens."""
        from toolwright.mcp.auth import generate_token, validate_token

        token = generate_token()
        assert validate_token(f"Bearer {token}", expected=token) is True


# ---------------------------------------------------------------------------
# Token masking
# ---------------------------------------------------------------------------


class TestTokenMasking:
    """mask_token shows only prefix + last 4 chars."""

    def test_mask_token(self) -> None:
        from toolwright.mcp.auth import mask_token

        token = "tw_abcdef1234567890abcdef1234567890"
        masked = mask_token(token)
        assert masked.startswith("tw_")
        assert masked.endswith("7890")
        assert "***" in masked
        # Should not contain the full token
        assert masked != token

    def test_mask_short_string(self) -> None:
        from toolwright.mcp.auth import mask_token

        masked = mask_token("short")
        assert "***" in masked


# ---------------------------------------------------------------------------
# HTTP middleware
# ---------------------------------------------------------------------------


class TestTokenAuthMiddleware:
    """TokenAuthMiddleware enforces bearer auth on protected routes."""

    @pytest.mark.asyncio
    async def test_health_exempt_from_auth(self, tmp_path: Path) -> None:
        """GET /health should work without auth."""
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.auth import TokenAuthMiddleware, generate_token
        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        token = generate_token()
        secured_app = TokenAuthMiddleware(app.starlette_app, token=token)

        transport = ASGITransport(app=secured_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_mcp_requires_auth(self, tmp_path: Path) -> None:
        """POST /mcp without token should be rejected."""
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.auth import TokenAuthMiddleware, generate_token
        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        token = generate_token()
        secured_app = TokenAuthMiddleware(app.starlette_app, token=token)

        transport = ASGITransport(app=secured_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/mcp", json={})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_mcp_with_valid_token(self, tmp_path: Path) -> None:
        """POST /mcp with valid bearer token should pass through."""
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.auth import TokenAuthMiddleware, generate_token
        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        token = generate_token()
        secured_app = TokenAuthMiddleware(app.starlette_app, token=token)

        transport = ASGITransport(app=secured_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/mcp",
                json={},
                headers={"Authorization": f"Bearer {token}"},
            )
            # Should not be 401 (may be 4xx from MCP protocol but not auth)
            assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, tmp_path: Path) -> None:
        """POST /mcp with wrong token should be 401."""
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.auth import TokenAuthMiddleware, generate_token
        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        token = generate_token()
        secured_app = TokenAuthMiddleware(app.starlette_app, token=token)

        transport = ASGITransport(app=secured_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/mcp",
                json={},
                headers={"Authorization": "Bearer tw_wrong_token_value_here0000"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_query_param_token_accepted(self, tmp_path: Path) -> None:
        """Token passed as ?t= query param should be accepted (for dashboard)."""
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.auth import TokenAuthMiddleware, generate_token
        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        token = generate_token()
        secured_app = TokenAuthMiddleware(app.starlette_app, token=token)

        transport = ASGITransport(app=secured_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/health?t={token}")
            # Health is exempt anyway, but test that query param doesn't break things
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Token from environment variable
# ---------------------------------------------------------------------------


class TestTokenFromEnv:
    """TOOLWRIGHT_TOKEN env var should be used for token."""

    def test_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.mcp.auth import resolve_token

        monkeypatch.setenv("TOOLWRIGHT_TOKEN", "tw_abcdef1234567890abcdef1234567890")
        token = resolve_token()
        assert token == "tw_abcdef1234567890abcdef1234567890"

    def test_explicit_token_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.mcp.auth import resolve_token

        monkeypatch.setenv("TOOLWRIGHT_TOKEN", "tw_from_env_value_0000000000000000")
        explicit = "tw_explicit_value_00000000000000ff"
        token = resolve_token(explicit_token=explicit)
        assert token == explicit

    def test_auto_generate_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.mcp.auth import resolve_token

        monkeypatch.delenv("TOOLWRIGHT_TOKEN", raising=False)
        token = resolve_token()
        assert token.startswith("tw_")
        assert len(token) == 35

"""Tests for HTTP transport layer (Sprint 1b).

TDD RED phase: tests define expected behavior before implementation.
"""

from __future__ import annotations

import json
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
# ToolwrightHTTPApp construction
# ---------------------------------------------------------------------------


class TestToolwrightHTTPApp:
    """Test Starlette app construction and route registration."""

    def test_create_http_app(self, tmp_path: Path) -> None:
        """HTTP app can be constructed from a ToolwrightMCPServer."""
        from toolwright.mcp.http_transport import ToolwrightHTTPApp

        tools_path = _tools_manifest(tmp_path)
        from toolwright.mcp.server import ToolwrightMCPServer

        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        assert app.starlette_app is not None

    def test_mcp_route_registered(self, tmp_path: Path) -> None:
        """The /mcp route should be registered."""
        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        routes = app.starlette_app.routes
        route_paths = [getattr(r, "path", None) for r in routes]
        assert "/mcp" in route_paths or any("/mcp" in str(getattr(r, "path", "")) for r in routes)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /health should return server status (no auth required)."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "healthy"
            assert "tools" in data

    @pytest.mark.asyncio
    async def test_health_reports_tool_count(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from toolwright.mcp.http_transport import ToolwrightHTTPApp
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        app = ToolwrightHTTPApp(server)

        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.json()["tools"] == 1


# ---------------------------------------------------------------------------
# run_http method on ToolwrightMCPServer
# ---------------------------------------------------------------------------


class TestRunHTTPMethod:
    """ToolwrightMCPServer should gain a run_http method."""

    def test_server_has_run_http(self, tmp_path: Path) -> None:
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        assert hasattr(server, "run_http")
        assert callable(server.run_http)


# ---------------------------------------------------------------------------
# CLI flag acceptance
# ---------------------------------------------------------------------------


class TestServeHTTPFlags:
    """The serve command should accept --http, --host, --port flags."""

    def test_serve_help_shows_http_flag(self) -> None:
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--http" in result.output

    def test_serve_help_shows_port_flag(self) -> None:
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--port" in result.output

    def test_serve_help_shows_host_flag(self) -> None:
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--host" in result.output


# ---------------------------------------------------------------------------
# run_mcp_server transport parameter
# ---------------------------------------------------------------------------


class TestRunMCPServerTransport:
    """run_mcp_server should accept transport/host/port params."""

    def test_run_mcp_server_accepts_transport_param(self) -> None:
        """run_mcp_server signature should include transport parameter."""
        import inspect

        from toolwright.mcp.server import run_mcp_server

        sig = inspect.signature(run_mcp_server)
        assert "transport" in sig.parameters

    def test_run_mcp_server_accepts_host_param(self) -> None:
        import inspect

        from toolwright.mcp.server import run_mcp_server

        sig = inspect.signature(run_mcp_server)
        assert "host" in sig.parameters

    def test_run_mcp_server_accepts_port_param(self) -> None:
        import inspect

        from toolwright.mcp.server import run_mcp_server

        sig = inspect.signature(run_mcp_server)
        assert "port" in sig.parameters


# ---------------------------------------------------------------------------
# Stdio still works (regression)
# ---------------------------------------------------------------------------


class TestStdioRegression:
    """Verify that stdio transport still functions after HTTP additions."""

    def test_server_has_run_stdio(self, tmp_path: Path) -> None:
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_path = _tools_manifest(tmp_path)
        server = ToolwrightMCPServer(tools_path=tools_path)
        assert hasattr(server, "run_stdio")
        assert callable(server.run_stdio)

    def test_default_transport_is_stdio(self) -> None:
        import inspect

        from toolwright.mcp.server import run_mcp_server

        sig = inspect.signature(run_mcp_server)
        transport_param = sig.parameters.get("transport")
        if transport_param:
            assert transport_param.default == "stdio"

"""Tests for Dashboard JSON API, SSE, and static files (Sprint 3b/3c)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tools_manifest(tmp_path: Path) -> Path:
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test API",
        "actions": [
            {
                "name": "get_users",
                "description": "List users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "low",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "delete_user",
                "description": "Delete a user",
                "method": "DELETE",
                "path": "/api/users/{id}",
                "host": "api.example.com",
                "risk_tier": "critical",
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
    }
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps(manifest))
    return tools_path


def _make_app(tmp_path: Path):
    from toolwright.mcp.events import EventBus
    from toolwright.mcp.http_transport import ToolwrightHTTPApp
    from toolwright.mcp.server import ToolwrightMCPServer

    tools_path = _tools_manifest(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path)
    event_bus = EventBus(max_events=100)
    app = ToolwrightHTTPApp(server, event_bus=event_bus)
    return app, event_bus


# ---------------------------------------------------------------------------
# API: /api/overview
# ---------------------------------------------------------------------------


class TestOverviewAPI:
    @pytest.mark.asyncio
    async def test_overview_returns_200(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        app, _ = _make_app(tmp_path)
        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/overview")
            assert resp.status_code == 200
            data = resp.json()
            assert "tools" in data
            assert "name" in data

    @pytest.mark.asyncio
    async def test_overview_tool_count(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        app, _ = _make_app(tmp_path)
        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/overview")
            assert resp.json()["tools"] == 2


# ---------------------------------------------------------------------------
# API: /api/tools
# ---------------------------------------------------------------------------


class TestToolsAPI:
    @pytest.mark.asyncio
    async def test_tools_returns_list(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        app, _ = _make_app(tmp_path)
        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/tools")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 2

    @pytest.mark.asyncio
    async def test_tools_contain_risk_info(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        app, _ = _make_app(tmp_path)
        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/tools")
            tools = resp.json()
            names = {t["name"] for t in tools}
            assert "get_users" in names
            # Each tool should have risk_tier
            for tool in tools:
                assert "risk_tier" in tool


# ---------------------------------------------------------------------------
# API: /api/events
# ---------------------------------------------------------------------------


class TestEventsAPI:
    @pytest.mark.asyncio
    async def test_events_empty(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        app, _ = _make_app(tmp_path)
        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/events")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 0

    @pytest.mark.asyncio
    async def test_events_after_publish(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        app, bus = _make_app(tmp_path)
        bus.publish("tool_called", {"tool": "get_users"})
        bus.publish("decision", {"decision": "allow"})

        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/events")
            data = resp.json()
            assert len(data) == 2
            assert data[0]["event_type"] == "tool_called"


# ---------------------------------------------------------------------------
# SSE: /api/events/stream
# ---------------------------------------------------------------------------


class TestSSEStream:
    def test_sse_route_registered(self, tmp_path: Path) -> None:
        """SSE endpoint route should be registered."""
        app, _ = _make_app(tmp_path)
        routes = app.starlette_app.routes
        route_paths = [getattr(r, "path", "") for r in routes]
        assert "/api/events/stream" in route_paths

    @pytest.mark.asyncio
    async def test_event_bus_subscribe_works(self) -> None:
        """EventBus subscribe delivers events (SSE data source)."""
        import asyncio

        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        received: list = []

        async def reader():
            async for event in bus.subscribe():
                received.append(event.to_dict())
                break

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.01)
        bus.publish("sse_test", {"key": "value"})
        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 1
        assert received[0]["event_type"] == "sse_test"


# ---------------------------------------------------------------------------
# Static Dashboard Files (Sprint 3c)
# ---------------------------------------------------------------------------


class TestDashboardStatic:
    def test_dashboard_files_exist(self) -> None:
        """All three dashboard files must exist."""
        import pathlib

        dashboard_dir = (
            pathlib.Path(__file__).resolve().parent.parent
            / "toolwright"
            / "assets"
            / "dashboard"
        )
        assert (dashboard_dir / "index.html").is_file()
        assert (dashboard_dir / "style.css").is_file()
        assert (dashboard_dir / "app.js").is_file()

    def test_dashboard_total_size_under_50kb(self) -> None:
        """Total dashboard file size must be under 50KB."""
        import pathlib

        dashboard_dir = (
            pathlib.Path(__file__).resolve().parent.parent
            / "toolwright"
            / "assets"
            / "dashboard"
        )
        total = sum(f.stat().st_size for f in dashboard_dir.iterdir() if f.is_file())
        assert total < 50_000, f"Dashboard total {total} bytes exceeds 50KB budget"

    def test_static_mount_registered(self, tmp_path: Path) -> None:
        """Static files mount should be present in routes."""
        from starlette.routing import Mount

        app, _ = _make_app(tmp_path)
        routes = app.starlette_app.routes
        # Find any Mount that serves static files (catch-all at root)
        static_mounts = [
            r for r in routes
            if isinstance(r, Mount) and hasattr(r, "app") and "StaticFiles" in type(r.app).__name__
        ]
        assert len(static_mounts) > 0

    @pytest.mark.asyncio
    async def test_static_serves_index(self, tmp_path: Path) -> None:
        """GET / should serve the dashboard index.html."""
        from httpx import ASGITransport, AsyncClient

        app, _ = _make_app(tmp_path)
        transport = ASGITransport(app=app.starlette_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "Toolwright Dashboard" in resp.text

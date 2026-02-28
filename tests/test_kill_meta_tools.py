"""Tests for KILL meta-tools exposed via the Meta MCP server.

Tests that the meta server exposes toolwright_kill_tool,
toolwright_enable_tool, and toolwright_quarantine_report tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer


@pytest.fixture
def tools_manifest(tmp_path: Path) -> Path:
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_user",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "low",
            },
        ],
    }
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(manifest))
    return p


@pytest.fixture
def meta_server(tools_manifest: Path, tmp_path: Path) -> ToolwrightMetaMCPServer:
    return ToolwrightMetaMCPServer(
        tools_path=str(tools_manifest),
        circuit_breaker_path=str(tmp_path / "breakers.json"),
    )


class TestKillMetaToolsRegistered:
    """KILL meta-tools should be listed."""

    @pytest.mark.asyncio
    async def test_kill_tool_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_kill_tool" in names

    @pytest.mark.asyncio
    async def test_enable_tool_not_listed(self, meta_server: ToolwrightMetaMCPServer):
        """toolwright_enable_tool removed: agents must not re-enable killed tools."""
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_enable_tool" not in names

    @pytest.mark.asyncio
    async def test_quarantine_report_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_quarantine_report" in names


class TestKillTool:
    """toolwright_kill_tool forces circuit breaker open."""

    @pytest.mark.asyncio
    async def test_kill_tool(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_kill_tool", {"tool_id": "get_user", "reason": "testing"}
        )
        data = json.loads(result[0].text)
        assert data["tool_id"] == "get_user"
        assert data["state"] == "open"

    @pytest.mark.asyncio
    async def test_kill_requires_tool_id(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_kill_tool", {}
        )
        data = json.loads(result[0].text)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_kill_without_circuit_breaker(self, tools_manifest: Path):
        """Server without circuit breaker configured should return error."""
        server = ToolwrightMetaMCPServer(tools_path=str(tools_manifest))
        result = await server._handle_call_tool(
            "toolwright_kill_tool", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert "error" in data


class TestEnableToolRemoved:
    """toolwright_enable_tool is removed: agents must not re-enable killed tools."""

    @pytest.mark.asyncio
    async def test_enable_tool_returns_unknown(self, meta_server: ToolwrightMetaMCPServer):
        """Calling the removed enable_tool should return an unknown-tool error."""
        result = await meta_server._handle_call_tool(
            "toolwright_enable_tool", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Unknown tool" in data["error"]


class TestQuarantineReport:
    """toolwright_quarantine_report lists tripped/killed tools."""

    @pytest.mark.asyncio
    async def test_empty_quarantine(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_quarantine_report", {}
        )
        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["tools"] == []

    @pytest.mark.asyncio
    async def test_quarantine_shows_killed_tool(self, meta_server: ToolwrightMetaMCPServer):
        await meta_server._handle_call_tool(
            "toolwright_kill_tool", {"tool_id": "get_user", "reason": "broken"}
        )
        result = await meta_server._handle_call_tool(
            "toolwright_quarantine_report", {}
        )
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["tools"][0]["tool_id"] == "get_user"

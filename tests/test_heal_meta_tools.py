"""Tests for HEAL meta-tools exposed via the Meta MCP server.

Tests that the meta server exposes toolwright_diagnose_tool,
toolwright_repair_tool, and toolwright_health_check tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer


@pytest.fixture
def tools_manifest(tmp_path: Path) -> Path:
    """Create a minimal tools manifest."""
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_user",
                "description": "Get user by ID",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "low",
                "input_schema": {
                    "type": "object",
                    "properties": {"user_id": {"type": "string"}},
                },
            },
        ],
    }
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(manifest))
    return p


@pytest.fixture
def meta_server(tools_manifest: Path) -> ToolwrightMetaMCPServer:
    return ToolwrightMetaMCPServer(tools_path=str(tools_manifest))


class TestHealMetaToolsRegistered:
    """HEAL meta-tools should be listed."""

    @pytest.mark.asyncio
    async def test_diagnose_tool_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_diagnose_tool" in names

    @pytest.mark.asyncio
    async def test_health_check_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_health_check" in names


class TestDiagnoseTool:
    """toolwright_diagnose_tool returns audit-based diagnosis."""

    @pytest.mark.asyncio
    async def test_diagnose_returns_result(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_diagnose_tool", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert "tool_id" in data
        assert data["tool_id"] == "get_user"

    @pytest.mark.asyncio
    async def test_diagnose_unknown_tool(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_diagnose_tool", {"tool_id": "nonexistent"}
        )
        data = json.loads(result[0].text)
        assert "tool_id" in data

    @pytest.mark.asyncio
    async def test_diagnose_requires_tool_id(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_diagnose_tool", {}
        )
        data = json.loads(result[0].text)
        assert "error" in data


class TestHealthCheck:
    """toolwright_health_check returns tool health status."""

    @pytest.mark.asyncio
    async def test_health_check_existing_tool(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_health_check", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert data["tool_id"] == "get_user"
        assert "exists" in data

    @pytest.mark.asyncio
    async def test_health_check_missing_tool(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_health_check", {"tool_id": "nonexistent"}
        )
        data = json.loads(result[0].text)
        assert data["exists"] is False

    @pytest.mark.asyncio
    async def test_health_check_requires_tool_id(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_health_check", {}
        )
        data = json.loads(result[0].text)
        assert "error" in data


class TestHealthCheckEndpointProbe:
    """health_check should probe the actual endpoint via HealthChecker."""

    @pytest.mark.asyncio
    async def test_health_check_probes_endpoint_healthy(
        self, meta_server: ToolwrightMetaMCPServer
    ):
        """When _send_probe returns 200, response includes endpoint_reachable=True."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(200, 42.5, None),
        ):
            result = await meta_server._handle_call_tool(
                "toolwright_health_check", {"tool_id": "get_user"}
            )
        data = json.loads(result[0].text)
        assert data["endpoint_reachable"] is True
        assert data["status_code"] == 200
        assert data["response_time_ms"] == 42.5
        assert data.get("failure_class") is None

    @pytest.mark.asyncio
    async def test_health_check_reports_endpoint_failure(
        self, meta_server: ToolwrightMetaMCPServer
    ):
        """When _send_probe returns 500, response includes failure_class."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(500, 100.0, None),
        ):
            result = await meta_server._handle_call_tool(
                "toolwright_health_check", {"tool_id": "get_user"}
            )
        data = json.loads(result[0].text)
        assert data["endpoint_reachable"] is False
        assert data["status_code"] == 500
        assert data["failure_class"] == "server_error"

    @pytest.mark.asyncio
    async def test_health_check_reports_network_error(
        self, meta_server: ToolwrightMetaMCPServer
    ):
        """When _send_probe returns a network error, response reflects it."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(None, 5000.0, "ConnectError: connection refused"),
        ):
            result = await meta_server._handle_call_tool(
                "toolwright_health_check", {"tool_id": "get_user"}
            )
        data = json.loads(result[0].text)
        assert data["endpoint_reachable"] is False
        assert data["failure_class"] == "network_unreachable"

    @pytest.mark.asyncio
    async def test_health_check_missing_tool_skips_probe(
        self, meta_server: ToolwrightMetaMCPServer
    ):
        """If tool doesn't exist in manifest, no endpoint probe."""
        result = await meta_server._handle_call_tool(
            "toolwright_health_check", {"tool_id": "nonexistent"}
        )
        data = json.loads(result[0].text)
        assert data["exists"] is False
        assert "endpoint_reachable" not in data


class TestDiagnoseToolEndpointProbe:
    """diagnose_tool should include endpoint probe in its diagnosis."""

    @pytest.mark.asyncio
    async def test_diagnose_includes_endpoint_status_healthy(
        self, meta_server: ToolwrightMetaMCPServer
    ):
        """Diagnosis includes endpoint_reachable when tool exists."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(200, 25.0, None),
        ):
            result = await meta_server._handle_call_tool(
                "toolwright_diagnose_tool", {"tool_id": "get_user"}
            )
        data = json.loads(result[0].text)
        assert data["endpoint_reachable"] is True
        assert len(data["issues"]) == 0

    @pytest.mark.asyncio
    async def test_diagnose_includes_endpoint_failure_issue(
        self, meta_server: ToolwrightMetaMCPServer
    ):
        """Diagnosis adds issue when endpoint is unreachable."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(404, 30.0, None),
        ):
            result = await meta_server._handle_call_tool(
                "toolwright_diagnose_tool", {"tool_id": "get_user"}
            )
        data = json.loads(result[0].text)
        assert data["endpoint_reachable"] is False
        assert any("endpoint" in issue.lower() for issue in data["issues"])

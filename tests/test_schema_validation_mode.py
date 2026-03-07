"""Tests for schema_validation mode on MCP server (F-018).

The schema_validation parameter controls whether outputSchema is advertised
to MCP clients, which determines if client-side response validation occurs.

Modes:
  strict - advertise outputSchema (client validates, current behavior)
  warn   - don't advertise outputSchema (no client validation), default
  off    - don't advertise outputSchema (no client validation)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import mcp.types as mcp_types
import pytest

from toolwright.mcp.server import ToolwrightMCPServer


def _write_tools_manifest(tmp_path: Path) -> Path:
    """Write a minimal tools.json with output_schema for testing."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Test Tools",
                "actions": [
                    {
                        "name": "get_users",
                        "description": "Get users",
                        "method": "GET",
                        "path": "/api/users",
                        "host": "api.example.com",
                        "risk_tier": "low",
                        "confirmation_required": "never",
                        "input_schema": {"type": "object", "properties": {}},
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "users": {"type": "array"},
                                "total": {"type": "integer"},
                            },
                            "required": ["users", "total"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tools_path


# --- schema_validation="strict": current behavior (advertise outputSchema) ---


@pytest.mark.asyncio
async def test_strict_mode_advertises_output_schema(tmp_path: Path) -> None:
    """In strict mode, outputSchema is set on the tool (client validates)."""
    tools_path = _write_tools_manifest(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="strict")
    handler = server.server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(params=None)

    result = await handler(req)
    payload = result.root
    assert isinstance(payload, mcp_types.ListToolsResult)
    assert payload.tools[0].outputSchema is not None


# --- schema_validation="warn": default (don't advertise outputSchema) ---


@pytest.mark.asyncio
async def test_warn_mode_omits_output_schema(tmp_path: Path) -> None:
    """In warn mode (default), outputSchema is NOT set (no client validation)."""
    tools_path = _write_tools_manifest(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="warn")
    handler = server.server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(params=None)

    result = await handler(req)
    payload = result.root
    assert isinstance(payload, mcp_types.ListToolsResult)
    assert payload.tools[0].outputSchema is None


@pytest.mark.asyncio
async def test_default_mode_is_warn(tmp_path: Path) -> None:
    """Default schema_validation should be 'warn' (lenient)."""
    tools_path = _write_tools_manifest(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path)
    assert server.schema_validation == "warn"


@pytest.mark.asyncio
async def test_warn_mode_still_returns_data(tmp_path: Path) -> None:
    """Even without outputSchema, tool calls still return response data."""
    tools_path = _write_tools_manifest(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="warn")
    handler = server.server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(name="get_users", arguments={})
    )

    response_data = {"users": [{"id": 1}]}
    with patch.object(server, "_execute_request", AsyncMock(return_value=response_data)):
        result = await handler(req)

    payload = result.root
    assert isinstance(payload, mcp_types.CallToolResult)
    assert payload.isError is False
    # In warn mode, no structuredContent (since outputSchema not advertised)
    # But data should still be returned as text content
    assert payload.content
    text = payload.content[0].text
    parsed = json.loads(text)
    assert parsed["users"] == [{"id": 1}]


# --- schema_validation="off": no outputSchema, no validation ---


@pytest.mark.asyncio
async def test_off_mode_omits_output_schema(tmp_path: Path) -> None:
    """In off mode, outputSchema is NOT set."""
    tools_path = _write_tools_manifest(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="off")
    handler = server.server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(params=None)

    result = await handler(req)
    payload = result.root
    assert isinstance(payload, mcp_types.ListToolsResult)
    assert payload.tools[0].outputSchema is None

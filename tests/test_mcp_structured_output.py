"""Tests for MCP structured output behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import mcp.types as mcp_types
import pytest

from toolwright.mcp.server import ToolwrightMCPServer


@pytest.mark.asyncio
async def test_mcp_tool_call_returns_structured_content_when_output_schema_defined(
    tmp_path: Path,
) -> None:
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
                            "properties": {"users": {"type": "array"}},
                            "required": ["users"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="strict")
    handler = server.server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(name="get_users", arguments={})
    )

    with patch.object(server, "_execute_request", AsyncMock(return_value={"users": []})):
        result = await handler(req)

    payload = result.root
    assert isinstance(payload, mcp_types.CallToolResult)
    assert payload.isError is False
    assert payload.structuredContent == {"users": []}


@pytest.mark.asyncio
async def test_mcp_tool_call_uses_wrapped_data_for_structured_output_when_output_schema_defined(
    tmp_path: Path,
) -> None:
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
                            "properties": {"users": {"type": "array"}},
                            "required": ["users"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="strict")
    handler = server.server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(name="get_users", arguments={})
    )

    wrapped = {
        "status": "success",
        "status_code": 200,
        "action": "get_users",
        "data": {"users": []},
    }
    with patch.object(server, "_execute_request", AsyncMock(return_value=wrapped)):
        result = await handler(req)

    payload = result.root
    assert isinstance(payload, mcp_types.CallToolResult)
    assert payload.isError is False
    assert payload.structuredContent == {"users": []}


@pytest.mark.asyncio
async def test_mcp_tool_call_bypasses_output_validation_on_http_error(
    tmp_path: Path,
) -> None:
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
                            "properties": {"users": {"type": "array"}},
                            "required": ["users"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="strict")
    handler = server.server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(name="get_users", arguments={})
    )

    wrapped = {
        "status": "success",
        "status_code": 403,
        "action": "get_users",
        "data": "Forbidden",
    }
    with patch.object(server, "_execute_request", AsyncMock(return_value=wrapped)):
        result = await handler(req)

    payload = result.root
    assert isinstance(payload, mcp_types.CallToolResult)
    assert payload.isError is True
    assert payload.structuredContent is None
    assert payload.content
    assert "403" in payload.content[0].text


@pytest.mark.asyncio
async def test_mcp_list_tools_omits_output_schema_for_non_object_output_schema(
    tmp_path: Path,
) -> None:
    """MCP outputSchema is only valid for structuredContent, which is object-only."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Test Tools",
                "actions": [
                    {
                        "name": "get_categories",
                        "description": "Get categories",
                        "method": "GET",
                        "path": "/api/categories",
                        "host": "api.example.com",
                        "risk_tier": "low",
                        "confirmation_required": "never",
                        "input_schema": {"type": "object", "properties": {}},
                        "output_schema": {"type": "array", "items": {"type": "string"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="strict")
    handler = server.server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(params=None)

    result = await handler(req)

    payload = result.root
    assert isinstance(payload, mcp_types.ListToolsResult)
    assert payload.tools
    assert payload.tools[0].outputSchema is None


@pytest.mark.asyncio
async def test_mcp_tool_call_returns_unstructured_text_for_non_object_payload_with_output_schema(
    tmp_path: Path,
) -> None:
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Test Tools",
                "actions": [
                    {
                        "name": "get_categories",
                        "description": "Get categories",
                        "method": "GET",
                        "path": "/api/categories",
                        "host": "api.example.com",
                        "risk_tier": "low",
                        "confirmation_required": "never",
                        "input_schema": {"type": "object", "properties": {}},
                        "output_schema": {"type": "array", "items": {"type": "string"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = ToolwrightMCPServer(tools_path=tools_path, schema_validation="strict")
    handler = server.server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(name="get_categories", arguments={})
    )

    wrapped = {
        "status": "success",
        "status_code": 200,
        "action": "get_categories",
        "data": ["a", "b"],
    }
    with patch.object(server, "_execute_request", AsyncMock(return_value=wrapped)):
        result = await handler(req)

    payload = result.root
    assert isinstance(payload, mcp_types.CallToolResult)
    assert payload.isError is False
    assert payload.structuredContent is None
    assert payload.content
    assert json.loads(payload.content[0].text) == ["a", "b"]

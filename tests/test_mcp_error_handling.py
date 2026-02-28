"""Tests for MCP error handling: unhandled exceptions become error responses."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import mcp.types as mcp_types
import pytest

from toolwright.mcp.server import ToolwrightMCPServer


@pytest.fixture
def minimal_tools_json(tmp_path: Path) -> Path:
    """Create a minimal tools.json for testing."""
    tools = {
        "schema_version": "1.0",
        "version": "1.0.0",
        "name": "Error Handling Tests",
        "actions": [
            {
                "name": "test_tool",
                "method": "GET",
                "path": "/test",
                "host": "api.example.com",
                "description": "A test tool",
                "risk_tier": "low",
                "confirmation_required": "never",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(tools), encoding="utf-8")
    return p


def _make_call_request(name: str, arguments: dict | None = None) -> mcp_types.CallToolRequest:
    """Helper to build a CallToolRequest."""
    return mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(
            name=name, arguments=arguments or {}
        )
    )


class TestMCPErrorHandling:
    """Unhandled exceptions in pipeline.execute should be wrapped as MCP errors."""

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_mcp_error(
        self, minimal_tools_json: Path
    ) -> None:
        """Pipeline exception should produce isError=True, not crash the server."""
        server = ToolwrightMCPServer(tools_path=minimal_tools_json)

        # Replace pipeline.execute with a function that always raises
        async def failing_execute(*args, **kwargs):
            raise RuntimeError("simulated crash")

        server.pipeline.execute = failing_execute  # type: ignore[assignment]

        handler = server.server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_request("test_tool")

        # Should return an MCP error response, not propagate the exception
        result = await handler(req)
        payload = result.root

        assert isinstance(payload, mcp_types.CallToolResult)
        assert payload.isError is True
        assert len(payload.content) >= 1
        text = payload.content[0].text
        assert "RuntimeError" in text
        assert "simulated crash" in text

    @pytest.mark.asyncio
    async def test_unhandled_exception_contains_exception_type(
        self, minimal_tools_json: Path
    ) -> None:
        """Error message should contain the exception class name."""
        server = ToolwrightMCPServer(tools_path=minimal_tools_json)

        async def failing_execute(*args, **kwargs):
            raise ValueError("bad argument")

        server.pipeline.execute = failing_execute  # type: ignore[assignment]

        handler = server.server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_request("test_tool", {"key": "value"})

        result = await handler(req)
        payload = result.root

        assert isinstance(payload, mcp_types.CallToolResult)
        assert payload.isError is True
        text = payload.content[0].text
        assert "ValueError" in text
        assert "bad argument" in text

    @pytest.mark.asyncio
    async def test_unhandled_exception_does_not_crash_server(
        self, minimal_tools_json: Path
    ) -> None:
        """Calling the handler after an error should still work (server not crashed)."""
        server = ToolwrightMCPServer(tools_path=minimal_tools_json)

        call_count = 0

        async def failing_then_ok(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first call fails")
            # Second call succeeds with a mock result
            from toolwright.mcp.pipeline import PipelineResult

            return PipelineResult(
                payload={"status": "ok"},
                is_error=False,
                is_structured=False,
                is_raw=True,
            )

        server.pipeline.execute = failing_then_ok  # type: ignore[assignment]

        handler = server.server.request_handlers[mcp_types.CallToolRequest]

        # First call: should return error, not crash
        req1 = _make_call_request("test_tool")
        result1 = await handler(req1)
        payload1 = result1.root
        assert isinstance(payload1, mcp_types.CallToolResult)
        assert payload1.isError is True

        # Second call: should succeed (server is still alive)
        req2 = _make_call_request("test_tool")
        result2 = await handler(req2)
        payload2 = result2.root
        # The MCP SDK wraps raw dicts; just verify no error
        if isinstance(payload2, mcp_types.CallToolResult):
            assert payload2.isError is False
        else:
            # Raw dict passthrough
            assert payload2 == {"status": "ok"}

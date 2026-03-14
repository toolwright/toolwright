"""Tests for CLI transport adapter.

Tests the JSONL protocol, tool listing, tool execution, and error handling.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from toolwright.cli_transport.adapter import CLITransportAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, actions: list[dict[str, Any]] | None = None) -> Path:
    if actions is None:
        actions = [
            {
                "name": "get_users",
                "tool_id": "sig_get_users",
                "description": "Get users",
                "method": "GET",
                "path": "/users",
                "host": "api.example.com",
                "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
                "risk_tier": "low",
            },
            {
                "name": "create_user",
                "tool_id": "sig_create_user",
                "description": "Create a user",
                "method": "POST",
                "path": "/users",
                "host": "api.example.com",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                "risk_tier": "medium",
            },
        ]
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "CLI Test Tools",
                "actions": actions,
            }
        )
    )
    return tools_path


def _make_runtime(tmp_path: Path, **kwargs: Any) -> Any:
    from toolwright.core.governance.runtime import GovernanceRuntime

    tools_path = _write_manifest(tmp_path)
    return GovernanceRuntime(
        tools_path=tools_path,
        transport_type="cli",
        **kwargs,
    )


def _make_adapter(tmp_path: Path, **kwargs: Any) -> CLITransportAdapter:
    runtime = _make_runtime(tmp_path, **kwargs)
    return CLITransportAdapter(runtime)


# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------


class TestCLITransportListTools:
    """Test list_tools method."""

    @pytest.mark.anyio
    async def test_list_tools_returns_all(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request({"method": "list_tools"})

        assert result["ok"] is True
        tools = result["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {"get_users", "create_user"}

    @pytest.mark.anyio
    async def test_list_tools_includes_schema(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request({"method": "list_tools"})

        tools = {t["name"]: t for t in result["result"]["tools"]}
        assert "limit" in tools["get_users"]["input_schema"]["properties"]


class TestCLITransportToolCall:
    """Test tool call handling."""

    @pytest.mark.anyio
    async def test_unknown_tool_error(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request(
            {"tool": "nonexistent", "args": {}}
        )

        assert result["ok"] is False
        assert "Unknown tool" in str(result["error"])

    @pytest.mark.anyio
    async def test_missing_tool_field_error(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request({"args": {"limit": 10}})

        assert result["ok"] is False
        assert "Missing" in result["error"]

    @pytest.mark.anyio
    async def test_invalid_args_type_error(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request(
            {"tool": "get_users", "args": "not_a_dict"}
        )

        assert result["ok"] is False
        assert "object" in result["error"]

    @pytest.mark.anyio
    async def test_tool_call_with_execute_fn(self, tmp_path: Path) -> None:
        mock_execute = AsyncMock(
            return_value={"status": 200, "body": '{"users": []}'}
        )
        adapter = _make_adapter(tmp_path, execute_request_fn=mock_execute)
        result = await adapter._handle_request(
            {"tool": "get_users", "args": {"limit": 10}}
        )

        # Result depends on decision engine (may deny without lockfile/policy),
        # but should not raise
        assert result is not None
        assert "ok" in result

    @pytest.mark.anyio
    async def test_dry_run_returns_result(self, tmp_path: Path) -> None:
        mock_execute = AsyncMock()
        adapter = _make_adapter(
            tmp_path, execute_request_fn=mock_execute, dry_run=True
        )
        result = await adapter._handle_request(
            {"tool": "get_users", "args": {}}
        )

        # Dry run should return a result without calling execute
        assert result is not None
        mock_execute.assert_not_called()


class TestCLITransportProtocol:
    """Test JSONL protocol handling."""

    @pytest.mark.anyio
    async def test_exit_method(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request({"method": "exit"})

        assert result["ok"] is True
        assert result["result"] == "bye"

    @pytest.mark.anyio
    async def test_quit_method(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        result = await adapter._handle_request({"method": "quit"})

        assert result["ok"] is True

    def test_write_response_jsonl(self) -> None:
        """Verify responses are valid JSONL."""
        output = StringIO()
        with patch("sys.stdout", output):
            CLITransportAdapter._write_response({"ok": True, "result": "test"})

        line = output.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["ok"] is True
        assert parsed["result"] == "test"

    def test_write_response_newline_terminated(self) -> None:
        output = StringIO()
        with patch("sys.stdout", output):
            CLITransportAdapter._write_response({"ok": True})

        assert output.getvalue().endswith("\n")


class TestCLITransportErrorHandling:
    """Test error handling in the adapter."""

    @pytest.mark.anyio
    async def test_non_dict_request_error(self, tmp_path: Path) -> None:
        """Non-object JSON should be rejected."""
        adapter = _make_adapter(tmp_path)
        # Simulate processing a non-dict (the main loop would catch this)
        output = StringIO()
        with patch("sys.stdout", output), patch(
            "sys.stdin",
            StringIO('"just a string"\n'),
        ):
            await adapter._run_async()

        line = output.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["ok"] is False
        assert "object" in parsed["error"]


class TestCLITransportConformance:
    """Verify CLI transport produces same governance decisions as MCP."""

    @pytest.mark.anyio
    async def test_transport_type_is_cli(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        assert adapter.runtime.transport_type == "cli"
        assert adapter.runtime.engine.transport_type == "cli"

    @pytest.mark.anyio
    async def test_unknown_tool_denied_same_as_mcp(self, tmp_path: Path) -> None:
        """CLI and MCP should both deny unknown tools with same error shape."""
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_manifest(tmp_path)

        # MCP transport
        mcp_runtime = GovernanceRuntime(
            tools_path=tools_path, transport_type="mcp"
        )
        mcp_result = await mcp_runtime.engine.execute("nonexistent", {})

        # CLI transport
        cli_runtime = GovernanceRuntime(
            tools_path=tools_path, transport_type="cli"
        )
        cli_result = await cli_runtime.engine.execute("nonexistent", {})

        # Both should be errors with same payload structure
        assert mcp_result.is_error == cli_result.is_error
        assert mcp_result.payload == cli_result.payload

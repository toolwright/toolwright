"""Tests for OverlayServer - MCP governance proxy."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def wrap_state_dir(tmp_path):
    """Create a temporary state directory for the overlay server."""
    state_dir = tmp_path / ".toolwright" / "wrap" / "test"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def mock_connection():
    """Create a mock WrappedConnection."""
    conn = AsyncMock()
    conn.is_connected = True
    conn.config = MagicMock()
    conn.config.server_name = "test"
    return conn


class TestOverlayServerInit:
    def test_creates_with_config(self, wrap_state_dir):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=["test"],
            state_dir=wrap_state_dir,
        )
        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)
        assert server.config.server_name == "test"


class TestOverlayServerProxyCall:
    @pytest.mark.asyncio
    async def test_proxy_call_normalizes_result(self, wrap_state_dir):
        """Proxy call should send to upstream and normalize the result."""
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )

        # Mock upstream returns a CallToolResult-like object
        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text='{"ok": true}')]
        mock_result.isError = False

        conn = AsyncMock()
        conn.call_tool = AsyncMock(return_value=mock_result)

        server = OverlayServer(config=config, connection=conn)

        action = {"name": "test_tool", "method": "MCP", "host": "test"}
        result = await server._proxy_call(action, {"arg1": "val1"})

        assert result["status_code"] == 200
        assert result["data"] == {"ok": True}
        assert result["action"] == "test_tool"
        conn.call_tool.assert_called_once_with("test_tool", {"arg1": "val1"})

    @pytest.mark.asyncio
    async def test_proxy_call_error_result(self, wrap_state_dir):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )

        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text="Connection refused")]
        mock_result.isError = True

        conn = AsyncMock()
        conn.call_tool = AsyncMock(return_value=mock_result)

        server = OverlayServer(config=config, connection=conn)

        action = {"name": "broken_tool", "method": "MCP", "host": "test"}
        result = await server._proxy_call(action, {})

        assert result["status_code"] == 500
        assert "Connection refused" in result["data"]


class TestOverlayServerActions:
    def test_builds_actions_from_approved_tools(self, wrap_state_dir):
        """Only approved tools in lockfile should appear in actions dict."""
        from toolwright.models.overlay import (
            DiscoveryResult,
            TargetType,
            WrapConfig,
            WrappedTool,
        )
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )

        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)

        # Simulate discovery result with 2 tools
        tools = [
            WrappedTool(
                name="list_files",
                description="List files",
                input_schema={"type": "object"},
                annotations={},
                risk_tier="low",
                tool_def_digest="abc123",
                confirmation_required="never",
            ),
            WrappedTool(
                name="delete_file",
                description="Delete a file",
                input_schema={"type": "object"},
                annotations={},
                risk_tier="critical",
                tool_def_digest="xyz789",
                confirmation_required="always",
            ),
        ]

        # Load all tools (no lockfile filtering - all treated as approved for this test)
        server.load_tools_from_discovery(
            DiscoveryResult(tools=tools, server_name="test"),
        )

        assert "list_files" in server.actions
        assert "delete_file" in server.actions
        assert server.actions["list_files"]["method"] == "MCP"
        assert server.actions["list_files"]["host"] == "test"

    def test_synthetic_action_has_correct_fields(self, wrap_state_dir):
        from toolwright.models.overlay import (
            DiscoveryResult,
            TargetType,
            WrapConfig,
            WrappedTool,
        )
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=[],
            state_dir=wrap_state_dir,
        )
        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)

        server.load_tools_from_discovery(
            DiscoveryResult(
                tools=[
                    WrappedTool(
                        name="list_repos",
                        description="List repositories",
                        input_schema={
                            "type": "object",
                            "properties": {"owner": {"type": "string"}},
                        },
                        annotations={},
                        risk_tier="low",
                        tool_def_digest="abc123",
                        confirmation_required="never",
                    ),
                ],
                server_name="github",
            ),
        )

        action = server.actions["list_repos"]
        assert action["name"] == "list_repos"
        assert action["tool_id"] == "list_repos"
        assert action["signature_id"] == "abc123"
        assert action["method"] == "MCP"
        assert action["path"] == "mcp://github/list_repos"
        assert action["host"] == "github"
        assert action["risk_tier"] == "low"
        assert action["description"] == "List repositories"
        assert action["input_schema"]["type"] == "object"


class TestOverlayServerLockfileIntegration:
    def test_sync_discovery_to_lockfile(self, wrap_state_dir):
        """Discovery results should sync to lockfile via sync_from_manifest."""
        from toolwright.models.overlay import (
            DiscoveryResult,
            TargetType,
            WrapConfig,
            WrappedTool,
        )
        from toolwright.overlay.discovery import build_synthetic_manifest
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )
        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)

        discovery = DiscoveryResult(
            tools=[
                WrappedTool(
                    name="list_files",
                    description="List files",
                    input_schema={"type": "object"},
                    annotations={},
                    risk_tier="low",
                    tool_def_digest="abc123",
                    confirmation_required="never",
                ),
                WrappedTool(
                    name="write_file",
                    description="Write a file",
                    input_schema={"type": "object"},
                    annotations={},
                    risk_tier="high",
                    tool_def_digest="def456",
                    confirmation_required="never",
                ),
            ],
            server_name="test",
        )

        manifest = build_synthetic_manifest(discovery, config)
        changes = server.sync_lockfile(manifest)

        assert "new" in changes
        assert len(changes["new"]) == 2
        assert "list_files" in changes["new"]
        assert "write_file" in changes["new"]

        # Lockfile should exist on disk
        assert config.lockfile_path.exists()

    def test_re_sync_detects_digest_change(self, wrap_state_dir):  # noqa: PLR0915
        """When tool digest changes, lockfile should mark for re-approval."""
        from toolwright.models.overlay import (
            DiscoveryResult,
            TargetType,
            WrapConfig,
            WrappedTool,
        )
        from toolwright.overlay.discovery import build_synthetic_manifest
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )
        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)

        # First sync
        discovery1 = DiscoveryResult(
            tools=[
                WrappedTool(
                    name="list_files",
                    description="List files",
                    input_schema={"type": "object"},
                    annotations={},
                    risk_tier="low",
                    tool_def_digest="digest_v1",
                    confirmation_required="never",
                ),
            ],
            server_name="test",
        )
        manifest1 = build_synthetic_manifest(discovery1, config)
        server.sync_lockfile(manifest1)

        # Second sync with changed digest
        discovery2 = DiscoveryResult(
            tools=[
                WrappedTool(
                    name="list_files",
                    description="List files v2",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
                    annotations={},
                    risk_tier="low",
                    tool_def_digest="digest_v2",
                    confirmation_required="never",
                ),
            ],
            server_name="test",
        )
        manifest2 = build_synthetic_manifest(discovery2, config)
        changes = server.sync_lockfile(manifest2)

        assert "modified" in changes
        assert "list_files" in changes["modified"]


class TestOverlayServerHandlers:
    """Tests for MCP handler registration and execution."""

    def _make_server(self, wrap_state_dir):
        from toolwright.models.overlay import (
            DiscoveryResult,
            TargetType,
            WrapConfig,
            WrappedTool,
        )
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )
        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)

        server.load_tools_from_discovery(
            DiscoveryResult(
                tools=[
                    WrappedTool(
                        name="list_files",
                        description="List files in a directory",
                        input_schema={
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                        annotations={},
                        risk_tier="low",
                        tool_def_digest="abc123",
                        confirmation_required="never",
                    ),
                    WrappedTool(
                        name="delete_file",
                        description="Delete a file",
                        input_schema={"type": "object"},
                        annotations={},
                        risk_tier="critical",
                        tool_def_digest="xyz789",
                        confirmation_required="always",
                    ),
                ],
                server_name="test",
            ),
        )
        return server, conn

    def test_register_handlers_creates_mcp_server(self, wrap_state_dir):
        """_register_handlers should create an MCP Server instance."""
        server, _ = self._make_server(wrap_state_dir)
        server._register_handlers()
        assert server._mcp_server is not None

    @pytest.mark.asyncio
    async def test_list_tools_handler_returns_all_actions(self, wrap_state_dir):
        """list_tools handler should return Tool objects for all loaded actions."""
        server, _ = self._make_server(wrap_state_dir)
        server._register_handlers()

        # Invoke the registered list_tools handler
        tools = await server._handle_list_tools()
        names = {t.name for t in tools}
        assert "list_files" in names
        assert "delete_file" in names
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_list_tools_includes_input_schema(self, wrap_state_dir):
        """list_tools should pass through input_schema from actions."""
        server, _ = self._make_server(wrap_state_dir)
        server._register_handlers()

        tools = await server._handle_list_tools()
        list_files = next(t for t in tools if t.name == "list_files")
        assert list_files.inputSchema["type"] == "object"
        assert "path" in list_files.inputSchema["properties"]

    @pytest.mark.asyncio
    async def test_call_tool_handler_delegates_to_pipeline(self, wrap_state_dir):
        """call_tool handler should invoke the pipeline and return MCP result."""
        from toolwright.mcp.pipeline import PipelineResult

        server, conn = self._make_server(wrap_state_dir)
        server._register_handlers()

        # Mock pipeline to return a success result
        mock_pipeline_result = PipelineResult.success({"files": ["a.txt", "b.txt"]})
        server._pipeline.execute = AsyncMock(return_value=mock_pipeline_result)

        result = await server._handle_call_tool(
            "list_files", {"path": "/tmp"}
        )

        server._pipeline.execute.assert_called_once_with(
            "list_files", {"path": "/tmp"}, toolset_name=None
        )
        # Should return a CallToolResult-like object
        assert hasattr(result, "content")
        assert result.isError is False

    @pytest.mark.asyncio
    async def test_call_tool_handler_error_result(self, wrap_state_dir):
        """call_tool handler should propagate errors from pipeline."""
        from toolwright.mcp.pipeline import PipelineResult

        server, _ = self._make_server(wrap_state_dir)
        server._register_handlers()

        mock_result = PipelineResult.error("Tool not allowed")
        server._pipeline.execute = AsyncMock(return_value=mock_result)

        result = await server._handle_call_tool(
            "list_files", {"path": "/tmp"}
        )

        assert result.isError is True
        assert "Tool not allowed" in result.content[0].text

    @pytest.mark.asyncio
    async def test_call_tool_handler_catches_exceptions(self, wrap_state_dir):
        """call_tool handler should catch exceptions and return error."""
        server, _ = self._make_server(wrap_state_dir)
        server._register_handlers()

        server._pipeline.execute = AsyncMock(side_effect=RuntimeError("boom"))

        result = await server._handle_call_tool(
            "list_files", {"path": "/tmp"}
        )

        assert result.isError is True
        assert "RuntimeError" in result.content[0].text


class TestOverlayServerFormatResult:
    """Tests for _format_mcp_result."""

    def _make_server(self, wrap_state_dir):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )
        return OverlayServer(config=config, connection=AsyncMock())

    def test_format_success_dict(self, wrap_state_dir):
        """Success dict payload should become JSON TextContent."""
        from toolwright.mcp.pipeline import PipelineResult

        server = self._make_server(wrap_state_dir)
        result = PipelineResult.success({"repos": ["a", "b"]})
        mcp_result = server._format_mcp_result(result)

        assert mcp_result.isError is False
        text = mcp_result.content[0].text
        assert json.loads(text) == {"repos": ["a", "b"]}

    def test_format_success_string(self, wrap_state_dir):
        """Success string payload should become TextContent as-is."""
        from toolwright.mcp.pipeline import PipelineResult

        server = self._make_server(wrap_state_dir)
        result = PipelineResult.success("Hello world")
        mcp_result = server._format_mcp_result(result)

        assert mcp_result.isError is False
        assert mcp_result.content[0].text == "Hello world"

    def test_format_error(self, wrap_state_dir):
        """Error result should set isError=True."""
        from toolwright.mcp.pipeline import PipelineResult

        server = self._make_server(wrap_state_dir)
        result = PipelineResult.error("denied by policy")
        mcp_result = server._format_mcp_result(result)

        assert mcp_result.isError is True
        assert "denied by policy" in mcp_result.content[0].text

    def test_format_raw_passthrough(self, wrap_state_dir):
        """Raw PipelineResult should be returned as-is."""
        from toolwright.mcp.pipeline import PipelineResult

        server = self._make_server(wrap_state_dir)
        raw_payload = {"already": "formatted"}
        result = PipelineResult.raw(raw_payload)
        mcp_result = server._format_mcp_result(result)

        assert mcp_result == raw_payload


class TestOverlayServerRunStdio:
    """Tests for run_stdio transport."""

    @pytest.mark.asyncio
    async def test_run_stdio_calls_server_run(self, wrap_state_dir):
        """run_stdio should use stdio_server and call server.run()."""
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.server import OverlayServer

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="echo",
            args=[],
            state_dir=wrap_state_dir,
        )
        conn = AsyncMock()
        server = OverlayServer(config=config, connection=conn)
        server._register_handlers()

        # Mock the stdio_server context manager and server.run
        mock_read = MagicMock()
        mock_write = MagicMock()
        server._mcp_server.run = AsyncMock()

        with patch(
            "toolwright.overlay.server.mcp_stdio.stdio_server"
        ) as mock_stdio:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def fake_stdio():
                yield (mock_read, mock_write)

            mock_stdio.side_effect = fake_stdio
            await server.run_stdio()

        server._mcp_server.run.assert_called_once()
        # First arg should be read stream, second write stream
        call_args = server._mcp_server.run.call_args
        assert call_args[0][0] is mock_read
        assert call_args[0][1] is mock_write

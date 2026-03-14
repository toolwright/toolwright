"""Tests for WrappedConnection - upstream MCP server connection management."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def stdio_config(tmp_path):
    from toolwright.models.overlay import TargetType, WrapConfig

    return WrapConfig(
        server_name="test-server",
        target_type=TargetType.STDIO,
        command="python",
        args=["-m", "test_server"],
        state_dir=tmp_path / "wrap" / "test-server",
    )


@pytest.fixture
def http_config(tmp_path):
    from toolwright.models.overlay import TargetType, WrapConfig

    return WrapConfig(
        server_name="sentry",
        target_type=TargetType.STREAMABLE_HTTP,
        url="https://mcp.sentry.dev/mcp",
        headers={"Authorization": "Bearer test"},
        state_dir=tmp_path / "wrap" / "sentry",
    )


class TestWrappedConnectionInit:
    def test_creates_with_stdio_config(self, stdio_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)
        assert conn.config == stdio_config
        assert conn.is_connected is False

    def test_creates_with_http_config(self, http_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(http_config)
        assert conn.config == http_config
        assert conn.is_connected is False


class TestWrappedConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect_and_close_stdio(self, stdio_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)

        # Mock the MCP SDK's stdio_client and ClientSession
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock(return_value=MagicMock())

        with patch(
            "toolwright.overlay.connection._connect_stdio",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            await conn.connect()
            assert conn.is_connected is True

            await conn.close()
            assert conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_and_close_http(self, http_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(http_config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock(return_value=MagicMock())

        with patch(
            "toolwright.overlay.connection._connect_http",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            await conn.connect()
            assert conn.is_connected is True

            await conn.close()
            assert conn.is_connected is False


class TestWrappedConnectionCalls:
    @pytest.mark.asyncio
    async def test_list_tools(self, stdio_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)

        mock_tool = MagicMock()
        mock_tool.name = "list_repos"
        mock_tool.description = "List repos"
        mock_tool.inputSchema = {"type": "object"}

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MagicMock(tools=[mock_tool])
        )

        with patch(
            "toolwright.overlay.connection._connect_stdio",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            await conn.connect()
            tools = await conn.list_tools()
            assert len(tools) == 1
            assert tools[0].name == "list_repos"
            await conn.close()

    @pytest.mark.asyncio
    async def test_call_tool(self, stdio_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)

        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text='{"ok": true}')]
        mock_result.isError = False

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        with patch(
            "toolwright.overlay.connection._connect_stdio",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            await conn.connect()
            result = await conn.call_tool("list_repos", {"owner": "test"})
            assert result.isError is False
            mock_session.call_tool.assert_called_once_with("list_repos", {"owner": "test"})
            await conn.close()

    @pytest.mark.asyncio
    async def test_call_tool_when_not_connected_raises(self, stdio_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)
        with pytest.raises(RuntimeError, match="not connected"):
            await conn.call_tool("test", {})

    @pytest.mark.asyncio
    async def test_call_tool_semaphore_bounds_concurrency(self, stdio_config):
        """Verify the semaphore limits concurrent calls."""
        import asyncio

        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)

        call_count = 0
        max_concurrent = 0

        async def slow_call(_name, _args):
            nonlocal call_count, max_concurrent
            call_count += 1
            current = call_count
            max_concurrent = max(max_concurrent, current)
            await asyncio.sleep(0.05)
            call_count -= 1
            return MagicMock(
                content=[MagicMock(type="text", text="ok")],
                isError=False,
            )

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = slow_call

        with patch(
            "toolwright.overlay.connection._connect_stdio",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            await conn.connect()
            # Override semaphore to a small number for testing
            conn._call_semaphore = asyncio.Semaphore(2)

            tasks = [conn.call_tool(f"tool_{i}", {}) for i in range(5)]
            await asyncio.gather(*tasks)

            # Max concurrent should never exceed semaphore limit
            assert max_concurrent <= 2
            await conn.close()


class TestWrappedConnectionReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_closes_and_reopens(self, stdio_config):
        from toolwright.overlay.connection import WrappedConnection

        conn = WrappedConnection(stdio_config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        connect_count = 0

        async def mock_connect_fn(_config, _stack):
            nonlocal connect_count
            connect_count += 1
            return mock_session

        with patch(
            "toolwright.overlay.connection._connect_stdio",
            new_callable=AsyncMock,
            side_effect=mock_connect_fn,
        ):
            await conn.connect()
            assert connect_count == 1

            await conn.reconnect()
            assert connect_count == 2
            assert conn.is_connected is True

            await conn.close()
